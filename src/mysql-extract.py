#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import logging
import types
import pymongo
import mongokit
import MySQLdb as mdb
from datetime import datetime
from pprint import pprint,pformat
from ConfigParser import SafeConfigParser

import catalog
from util import *

import sql2mongo

import workload
LOG = logging.getLogger(__name__)

## ==============================================
## main
## ==============================================
if __name__ == '__main__':
    aparser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                      description="%s\n%s" % (constants.PROJECT_NAME, constants.PROJECT_URL))
    aparser.add_argument('--config', type=file,
                         help='Path to %s configuration file' % constants.PROJECT_NAME)
    aparser.add_argument('--host', type=str, help='MySQL host name')
    aparser.add_argument('--name', type=str, help='MySQL database name')
    aparser.add_argument('--user', type=str, help='MySQL username')
    aparser.add_argument('--pass', type=str, help='MySQL password')
    aparser.add_argument('--debug', action='store_true',
                         help='Enable debug log messages')
    args = vars(aparser.parse_args())

    if args['debug']: logging.getLogger().setLevel(logging.DEBUG)

    if not args['config']:
        logging.error("Missing configuration file")
        print
        aparser.print_help()
        sys.exit(1)
    logging.debug("Loading configuration file '%s'" % args['config'])
    cparser = SafeConfigParser()
    cparser.read(os.path.realpath(args['config'].name))
    config.setDefaultValues(cparser)
    
    ## ----------------------------------------------
    
    ## Connect to MongoDB
    try:
        hostname = cparser.get(config.SECT_MONGODB, 'hostname')
        port = cparser.getint(config.SECT_MONGODB, 'port')        
        conn = mongokit.Connection(host=hostname, port=port)
        mongo_conn = pymongo.Connection(host=hostname, port=port)
        db = mongo_conn[cparser.get(config.SECT_MONGODB, 'dataset_db')]
    except:
        LOG.error("Failed to connect to MongoDB at %s:%s" % (config['hostname'], config['port']))
        raise
    
    ## Register our objects with MongoKit
    conn.register([ catalog.Collection ])
    metadata_db = conn[cparser.get(config.SECT_MONGODB, 'metadata_db')]
    metadata_db.drop_collection(constants.COLLECTION_SCHEMA)
    ## ----------------------------------------------
    
    mysql_conn = mdb.connect(host=args['host'], db=args['name'], user=args['user'], passwd=args['pass'])
    c1 = mysql_conn.cursor()
    c1.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME <> 'general_log'", args['name'])
    quick_look = {}
    for row in c1:
        tbl_name = row[0]
        print tbl_name
        coll_catalog = metadata_db.Collection()
        coll_catalog['name'] = unicode(tbl_name)
        coll_catalog['shard_keys'] = { }
        coll_catalog['fields'] = { }
        coll_catalog['indexes'] = { }
        quick_look[coll_catalog['name']] = []
        
        c2 = mysql_conn.cursor()
        c2.execute("""
            SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME=%s
        """, (args['name'], tbl_name))
        
        for col_row in c2:
            col_name = col_row[0]
            quick_look[coll_catalog['name']].append(col_name)
            col_type = catalog.sqlTypeToPython(col_row[1])
            coll_catalog["fields"][col_name] = {
                'type': catalog.fieldTypeToString(col_type),
                'query_use_count' : 0,
                'hist_query_keys' : [],
                'hist_query_values' : [],
                'hist_data_keys' : [],
                'hist_data_values' : [],
                'max' : None,
                'min' : None,
            }
        ## FOR
        
        # Get the index information from MySQL for this table
        sql = "SHOW INDEXES FROM " + args['name'] + "." + tbl_name
        c3 = mysql_conn.cursor()
        c3.execute(sql)
        index_name = None
        for ind_row in c3:
            if index_name <> ind_row[2]:
                coll_catalog['indexes'][ind_row[2]] = []
                index_name = ind_row[2]
            coll_catalog['indexes'][ind_row[2]].append(ind_row[4])
        ## FOR
        coll_catalog.validate()
        coll_catalog.save()
        
        collection = db[tbl_name]
        collection.remove()
        sql = 'SELECT * FROM ' + args['name'] + '.' + tbl_name
        c4 = mysql_conn.cursor()
        c4.execute(sql)
        for data_row in c4 :
            mongo_record = {}
            i = 0
            for column in quick_look[tbl_name] :
                mongo_record[column] = data_row[i]
                i += 1
            ## ENDFOR
            collection.insert(mongo_record)
        ## ENDFOR
    ## ENDFOR

    # Ingest a MySQL query log and convert it into our workload.Sessions objects
    c4 = mysql_conn.cursor()
    c4.execute("""
        SELECT * FROM general_log ORDER BY thread_id, event_time;	
    """)
    conn.register([workload.Session])
    metadata_db.drop_collection(constants.COLLECTION_WORKLOAD)
    
    thread_id = None
    first = True
    uid = 0
    hostIP = sql2mongo.detectHostIP()
    mongo = sql2mongo.Sql2mongo(quick_look)
    for row in c4:
        stamp = float(row[0].strftime("%s"))
        if row[2] <> thread_id :
            thread_id = row[2]
            if first == False :
                if len(session['operations']) > 0 :
                    session.save()
                    uid += 1
                ## ENDIF
            else :
                first = False
            ## ENDIF
            session = metadata_db.Session()
            session['ip1'] = sql2mongo.stripIPtoUnicode(row[1])
            session['ip2'] = hostIP
            session['uid'] = uid
            session['operations'] = []
        ## ENDIF
        if row[5] <> '' :
            print row[5]
            query = mongo.process_sql(row[5])
            if mongo.query_type <> 'UNKNOWN' : 
                operations = mongo.generate_operations(stamp)
                print mongo.render_mongo_command()
                for op in operations :
                    session['operations'].append(op)
                ## ENDFOR
            elif row[5].strip().lower() == 'commit' :
                if len(session['operations']) > 0 :
                    session.save()
                    uid += 1
                ## ENDIF
                session = metadata_db.Session()
                session['ip1'] = sql2mongo.stripIPtoUnicode(row[1])
                session['ip2'] = hostIP
                session['uid'] = uid
                session['operations'] = []
            ## ENDIF
        ## ENDIF
    ## ENDFOR
    session.save()
## MAIN