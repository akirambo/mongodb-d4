# -*- coding: utf-8 -*-

import sys
import logging
import types
from datetime import datetime
from pprint import pformat

import traces

LOG = logging.getLogger(__name__)

# TODO: This is just for testing that our Sessions object
# validates correctly. The parser/santizer should be fixed
# to use the Sessions object directly
def convertWorkload(conn):
    old_workload = conn['designer']['mongo_comm']
    new_workload = ['workload']
    
    new_sess = conn['designer'].Session()
    new_sess['ip1'] = u'127.0.0.1:59829'
    new_sess['ip2'] = u'127.0.0.1:27017'
    
    for trace in old_workload.find({'IP1': new_sess['ip1'], 'IP2': new_sess['ip2']}):
        new_sess['uid'] = trace['uid']
        if not trace['content']: continue
        
        assert len(trace['content']) == 1, pformat(trace['content'])
        #print "CONTENT:", pformat(trace['content'])
        op = {
            'collection': trace['collection'],
            'content':    trace['content'][0],
            'timestamp':  float(trace['timestamp']),
            'type':       trace['type'],
            'size':       int(trace['size'].replace("bytes", "")),
        }
        new_sess['operations'].append(op)
    ## FOR
    
    print new_sess
    new_sess.save()
## DEF