#!/usr/bin/env python
import sys
import fileinput
import hashlib
import time
import re
import argparse
import yaml
import json
import logging
import workload_info
from pymongo import Connection

sys.path.append("../workload")
from traces import *

logging.basicConfig(level = logging.INFO,
                    format="%(asctime)s [%(funcName)s:%(lineno)03d] %(levelname)-5s: %(message)s",
                    datefmt="%m-%d-%Y %H:%M:%S",
                    stream = sys.stdout)
LOG = logging.getLogger(__name__)

### DEFAULT VALUES
### you can specify these with args
INPUT_FILE = "sample.txt"
WORKLOAD_DB = "metadata"
WORKLOAD_COLLECTION = "workload01"
INITIAL_SESSION_UID = 100 #where to start the incremental session uid
DEFAULT_HOST = "localhost"
DEFAULT_PORT = "27017"

###GLOBAL VARS
connection = None
current_transaction = None
workload_db = None
workload_col = None
recreated_db = None

current_session_map = {}
session_uid = INITIAL_SESSION_UID

query_response_map = {}

### parsing regexp masks
### parts of header
TIME_MASK = "[0-9]+\.[0-9]+.*"
ARROW_MASK = "(-->>|<<--)"
IP_MASK = "\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{5,5}"
COLLECTION_MASK = "[\w+\.]+\$?\w+"
SIZE_MASK = "\d+ bytes"
MAGIC_ID_MASK = "id:\w+"
TRANSACTION_ID_MASK = "\d+"
REPLY_ID_MASK = "\d+"
### header
HEADER_MASK = "(?P<timestamp>" + TIME_MASK + ") *- *" + \
"(?P<IP1>" + IP_MASK + ") *" + \
"(?P<arrow>" + ARROW_MASK + ") *" + \
"(?P<IP2>" + IP_MASK + ") *" + \
"(?P<collection>" + COLLECTION_MASK + ")? *" + \
"(?P<size>" + SIZE_MASK + ") *" + \
"(?P<magic_id>" + MAGIC_ID_MASK + ")[\t ]*" + \
"(?P<trans_id>" + TRANSACTION_ID_MASK + ")[\t ]*" + \
"-?[\t ]*(?P<query_id>" + REPLY_ID_MASK + ")?"
headerRegex = re.compile(HEADER_MASK);
### content lines
CONTENT_REPLY_MASK = "\s*reply +.*"
CONTENT_INSERT_MASK = "\s*insert: {.*"
CONTENT_QUERY_MASK = "\s*query: {.*"
CONTENT_UPDATE_MASK = "\s*update .*"
CONTENT_DELETE_MASK = "\s*delete .*"

replyRegex = re.compile(CONTENT_REPLY_MASK)
insertRegex = re.compile(CONTENT_INSERT_MASK)
queryRegex = re.compile(CONTENT_QUERY_MASK)
updateRegex = re.compile(CONTENT_UPDATE_MASK)
deleteRegex = re.compile(CONTENT_DELETE_MASK)

# other masks for parsing
FLAGS_MASK = ".*flags:(?P<flags>\d).*" #vals: 0,1,2,3
flagsRegex = re.compile(FLAGS_MASK)
NTORETURN_MASK = ".*ntoreturn: (?P<ntoreturn>-?\d+).*" # int 
ntoreturnRegex = re.compile(NTORETURN_MASK)
NTOSKIP_MASK = ".*ntoskip: (?P<ntoskip>\d+).*" #int
ntoskipRegex = re.compile(NTOSKIP_MASK)

# op TYPES
TYPE_QUERY = '$query'
TYPE_INSERT = '$insert'
TYPE_DELETE = '$delete'
TYPE_UPDATE = '$update'
TYPE_REPLY = '$reply'
QUERY_TYPES = [TYPE_QUERY, TYPE_INSERT, TYPE_DELETE, TYPE_UPDATE]

#returns collection where the traces (Session objects) are stored
def getTracesCollection():
    return workload_db[workload_col]

def initDB(hostname, port, w_db, w_col):
    global connection
    global workload_db
    global workload_col

    LOG.info("Connecting to MongoDB at %s:%d" % (hostname, port))
    
    # Initialize connection to db that stores raw transactions
    connection = Connection(hostname, port)
    workload_db = connection[w_db]
    workload_col = w_col

    return

def cleanWorkload():
    getTracesCollection().remove()


# helper method to split IP and port
def getOnlyIP(ipAndPort):
    l = ipAndPort.rsplit(":") # we can be sure that ipAndPort is in the form of IP:port since it was matched by regex...
    return l[0]

#
# this function initializes a new Session() object (in workload/traces.py)
# and sotres it in the collection
# ip1 is the key in current_transaction_map
#
def addSession(ip_client, ip_server):
    global current_session_map
    global session_uid
    global workload_db
        
        #verify a session with the uid does not exist
    if getTracesCollection().find({'session_id': session_uid}).count() > 0:
        LOG.error("Error: Session with UID %s already exists." % session_uid)
        LOG.error("Maybe you want to clean the database / use a different collection?")
        sys.exit(0)

    session = Session()
    session['ip_client'] = unicode(ip_client)
    session['ip_server'] = unicode(ip_server)
    session['session_id'] = session_uid
    current_session_map[ip_client] = session
    session_uid = session_uid + 1
    getTracesCollection().save(session)
    return session

def store(transaction):
    #print ""
    #print ""
    #print current_transaction
    if (current_transaction['arrow'] == '-->>'):
        ip_client = current_transaction['IP1']
        ip_server = current_transaction['IP2']
    else:
        ip_client = current_transaction['IP2']
        ip_server = current_transaction['IP1']

    if (ip_client not in current_session_map):
        session = addSession(ip_client, ip_server)
    else:
        session = current_session_map[ip_client]
    
    if 'type' not in current_transaction:
        LOG.error("INCOMPLETE operation:")
        LOG.error(current_transaction)
        return
    
    # QUERY: $query, $delete, $insert, $update:
    # Create the operation, add it to the session
    if current_transaction['type'] in QUERY_TYPES:
        # create the operation -- corresponds to current_transaction
        query_id = current_transaction['trans_id'];
        op = {
                'collection': unicode(current_transaction['collection']),
                'type': unicode(current_transaction['type']),
                'query_time': float(current_transaction['timestamp']),
                'query_size': int(current_transaction['size'].replace("bytes", "")),
                'query_content': current_transaction['content'],
                'query_id': int(query_id)
        }
        # update flags
        if current_transaction['type'] == TYPE_UPDATE:
            op['update_upsert'] = current_transaction['update_upsert']
            op['update_multi'] = current_transaction['update_multi']
        # query - SKIP, LIMIT
        if current_transaction['type'] == TYPE_QUERY:
            op['query_limit'] = int(current_transaction['ntoreturn']['ntoreturn'])
            op['query_offset'] = int(current_transaction['ntoskip']['ntoskip'])
            
        query_response_map[query_id] = op
        # append it to the current session
        session['operations'].append(op)
        LOG.debug("added operation: %s" % op)
    
    # RESPONSE - add information to the matching query
    if current_transaction['type'] == "$reply":
        query_id = current_transaction['query_id'];
        # see if the matching query is in the map
        if query_id in query_response_map:
            # fill in missing information
            query_op = query_response_map[query_id]
            query_op['resp_content'] = unicode(current_transaction['content'])
            query_op['resp_size'] = int(current_transaction['size'].replace("bytes", ""))
            query_op['resp_time'] = float(current_transaction['timestamp'])
            query_op['resp_id'] = int(current_transaction['trans_id'])    
        else:
            print "SKIPPING RESPONSE (no matching query_id): ", query_id
            
    #save the current session
    getTracesCollection().save(session)
    
    LOG.debug("session %d was updated" % session['session_id'])
    return


def process_header_line(header):
    global current_transaction

    if (current_transaction):
        store(current_transaction)

    current_transaction = header
    current_transaction['content'] = []
    
    return


# helper function for process_content_line 
# takes yaml {...} as input
# parses the input to JSON and adds that to current_transaction['content']
def add_yaml_to_content(yaml_line):
    global current_transaction
    
    yaml_line = yaml_line.strip()
    
    #skip empty lines
    if len(yaml_line) == 0:
        return

    if not yaml_line.startswith("{"):
        # this is not a content line... it can't be yaml
        print "ERROR: JSON does not start with {:"
        print yaml_line
        return
    
    if not yaml_line.strip().endswith("}"):
        print "ERROR: JSON does not end with }:"
        print yaml_line
        return    
    
    
    #yaml parser might fail :D
    try:
        obj = yaml.load(yaml_line)
    except (yaml.scanner.ScannerError, yaml.parser.ParserError, yaml.reader.ReaderError) as err:
        LOG.error("Parsing yaml to JSON: " + str(yaml_line))
        LOG.error("details: " + str(err))
        #print yaml_line
        #exit()
        return
    valid_json = json.dumps(obj)
    obj = yaml.load(valid_json)
    if not obj:
        LOG.error("Weird error. This line parsed to yaml, not to JSON: " + str(yaml_line))
        return 
    
    #if this is the first time we see this session, add it
    if ('whatismyuri' in obj):
        addSession(current_transaction['ip_client'], current_transaction['ip_server'])
    
    #store the line
    current_transaction['content'].append(obj)
    return

# takes any line which does not pass as header line
# tries to figure out the transaction type & store the content
def process_content_line(line):
    global current_transaction
    
    # ignore content lines before the first transaction is started
    if (not current_transaction):
        return

    # REPLY
    if (replyRegex.match(line)):
        current_transaction['type'] = TYPE_REPLY
    
    #INSERT
    elif (insertRegex.match(line)):
        current_transaction['type'] = TYPE_INSERT
        line = line[line.find('{'):line.rfind('}')+1]
        add_yaml_to_content(line)
    
    # QUERY
    elif (queryRegex.match(line)):
        current_transaction['type'] = TYPE_QUERY
        
        # extract OFFSET and LIMIT
        current_transaction['ntoskip'] = ntoskipRegex.match(line).groupdict()
        current_transaction['ntoreturn'] = ntoreturnRegex.match(line).groupdict()
        
        line = line[line.find('{'):line.rfind('}')+1]
        add_yaml_to_content(line)
        
    # UPDATE
    elif (updateRegex.match(line)):
        current_transaction['type'] = TYPE_UPDATE
        
        # extract FLAGS
        upsert=False
        multi=False
        flags = flagsRegex.match(line).groupdict()
        if flags=='1':
            upsert=True
            multi=False
        if flags=='2':
            upsert=False
            multi=True
        if flags=='3':
            upsert=True
            multi=True
        current_transaction['update_upsert']=upsert
        current_transaction['update_multi']=multi
        
        # extract the CRITERIA and NEW_OBJ
        lines = line[line.find('{'):line.rfind('}')+1].split(" o:")
        if len(lines) > 2:
            LOG.error("Fuck. This update query is tricky to parse: " + str(line))
            LOG.error("Skipping it for now...")
        if len(lines) < 2:
            return
        add_yaml_to_content(lines[0])
        add_yaml_to_content(lines[1])
    
    # DELETE
    elif (deleteRegex.match(line)):
        current_transaction['type'] = TYPE_DELETE
        line = line[line.find('{'):line.rfind('}')+1] 
        add_yaml_to_content(line) 
    
    # GENERIC CONTENT LINE
    else:
        #default: probably just yaml content line...
        add_yaml_to_content(line) 
    return

def parseFile(file):
    LOG.info("Processing file %s...", file)
    file = open(file, 'r')
    line = file.readline()
    trans_cnt = 0
    
    while line:
        result = headerRegex.match(line)
        #print line
        if result:
            process_header_line(result.groupdict())
            trans_cnt += 1
        else:
            process_content_line(line)
        line = file.readline()

    if (current_transaction):
        store(current_transaction)

    print ""
    session_cnt = INITIAL_SESSION_UID - session_uid
    LOG.info("Done. Added [%d traces], [%d sessions] to '%s'" % (trans_cnt, session_cnt, workload_col))
        


# STATS - print out some information when parsing finishes
def print_stats(args):
    workload_info.print_stats(args['host'], args['port'], args['workload_db'], args['workload_col'])

def main():
    global current_transaction
    global headerRegex

    aparser = argparse.ArgumentParser(description='MongoDesigner Trace Parser')
    aparser.add_argument('--host',
                         help='hostname of machine running mongo server', default=DEFAULT_HOST)
    aparser.add_argument('--port', type=int,
                         help='port to connect to', default=DEFAULT_PORT)
    aparser.add_argument('--file',
                         help='file to read from', default=INPUT_FILE)
    aparser.add_argument('--workload_db', help='the database where you want to store the traces', default=WORKLOAD_DB)
    aparser.add_argument('--workload_col', help='the collection where you want to store the traces', default=WORKLOAD_COLLECTION)
    aparser.add_argument('--clean', action='store_true',
                         help='Remove all documents in the workload collection before processing is started')    
    args = vars(aparser.parse_args())

    print ""
    LOG.info("..:: MongoDesigner Trace Parser ::..")
    print ""

    settings = "host: ", args['host'], " port: ", args['port'], " file: ", args['file'], " db: ", args['workload_db'], " col: ", args['workload_col']
    LOG.info("Settings: %s", settings)

    # initialize connection to MongoDB
    initDB(args['host'], args['port'], args['workload_db'], args['workload_col'])

    # wipe the collection
    if args['clean']:
        LOG.warn("Cleaning '%s' collection...", workload_col)
        cleanWorkload()
    
    # parse
    parseFile(args['file'])
    
    # print info
    print_stats(args)
    
    return


if __name__ == '__main__':
        main()



    
