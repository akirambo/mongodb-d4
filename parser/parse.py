#!/usr/bin/env python
import sys
import fileinput
import hashlib
import time
import re
from pymongo import Connection

###GLOBAL VARS
current_transaction = None
mongo_comm = None

INPUT_FILE = "sample.txt"


###REGEX STUFF
TIME_MASK = "[0-9]+\.[0-9]+.*"
ARROW_MASK = "(-->>|<<--)"
IP_MASK = "\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{5,5}"
COLLECTION_MASK = "\w+\.\$?\w+"
SIZE_MASK = "\d+ bytes"
MAGIC_ID_MASK = "id:\w+ \d+"
REPLY_ID_MASK = "\d+"

HEADER_MASK = "(?P<timestamp>" + TIME_MASK + ") *- *" + \
"(?P<IP1>" + IP_MASK + ") *" + \
"(?P<arrow>" + ARROW_MASK + ") *" + \
"(?P<IP2>" + IP_MASK + ") *" + \
"(?P<collection>" + COLLECTION_MASK + ")? *" + \
"(?P<size>" + SIZE_MASK + ") *" + \
"(?P<magic_id>" + MAGIC_ID_MASK + ") *" + \
"-? *(?P<reply_id>" + REPLY_ID_MASK + ")?"

CONTENT_REPLY_MASK = "\s*reply +.*"
CONTENT_INSERT_MASK = "\s*insert: {.*"
CONTENT_QUERY_MASK = "\s*query: {.*"
replyRegex = re.compile(CONTENT_REPLY_MASK)
insertRegex = re.compile(CONTENT_INSERT_MASK)
queryRegex = re.compile(CONTENT_QUERY_MASK)

def initDB():
    global mongo_comm
    connection = Connection()
    db = connection.mongo_designer
    mongo_comm = db.mongo_comm
    return


def store(transaction):
    global mongo_comm
    mongo_comm.insert(transaction)
    return

def process_header_line(header):
    global current_transaction

    if (current_transaction):
        store(current_transaction)

    current_transaction = header
    current_transaction['content'] = []
    return

def process_content_line(line):
    global replyRegex
    global insertRegex
    global queryRegex
    global current_transaction

    if (not current_transaction):
        return

    if (replyRegex.match(line)):
        current_transaction['type'] = "reply"
        print("reply")
    elif (insertRegex.match(line)):
        current_transaction['type'] = "insert"
        print("insert")
    elif (queryRegex.match(line)):
        current_transaction['type'] = "query"
        print("query")
    else:
        current_transaction['content'].append(line)
        print("other")

    return

def main():
    global current_transaction

    initDB()

    header_regex = re.compile(HEADER_MASK);

    file = open(INPUT_FILE, 'r')
    line = file.readline()
    while line:
        line = file.readline()
        result = header_regex.match(line)
        if result:
            process_header_line(result.groupdict())
        else:
            process_content_line(line)

    return


if __name__ == '__main__':
	main()



    
