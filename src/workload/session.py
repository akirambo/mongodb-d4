# -*- coding: utf-8 -*-

from mongokit import Document
from mongokit import IS
import sys
sys.path.append("../")
from util import constants

## ==============================================
## Session
## ==============================================
class Session(Document):
    __collection__ = constants.COLLECTION_WORKLOAD
    structure = {
        'session_id':  int,      # unique identifier for this session
        'ip_client':   basestring,  # IP:port of the client
        'ip_server':   basestring,  # IP:port of the mongo server
        'start_time':  float,    # The relative timestamp of when this session began (in seconds)
        'end_time':    float,    # The relative timestamp of when this session finished (in seconds)
        
        ## ----------------------------------------------
        ## OPERATIONS
        ## These are all of the queries that the client executed
        ## during the session.
        ## ----------------------------------------------
        'operations': [
            {
                # The name of the collection targeted in this operation
                'collection':       basestring,
                # The type of the query ($delete, $insert, $update, $query)
                # See OPT_TYPE_* in util/constants.py
                'type':             basestring, # IS(constants.OP_TYPE_ALL),

                ## ----------------------------------------------
                ## QUERY ATTRIBUTES
                ## ----------------------------------------------

                # The relative timestamp of when the query was sent to the server (in seconds)
                'query_time':       float,
                # Query payload (BSON)
                'query_content':    list,
                # Query payload size [bytes]
                'query_size':       int,
                # Unique identifier of this query invocation
                # query_id and resp_id are used to pair up queries & responses
                'query_id':         int,

                # A hash code compute from this query's payload signature. Different
                # invocations of queries that reference the same keys in this collection
                # but have different input parameters will have the same hash
                # See workload/ophasher.py
                'query_hash':       long,

                # mysql
                'query_group':      int,        # mysql split join

                # query flags & props
                # flags: 1==upsert:TRUE, multi:FALSE, 2==upsert:FALSE, multi:TRUE
                'update_upsert':    bool,    # T/F from flags
                'update_multi':     bool,    # T/F from flags
                'query_limit':      int,     # ntoreturn, -1: all
                'query_offset':     int,     # ntoskip
                'query_aggregate':  bool,    # T/F aggregate yes or no

                ## ----------------------------------------------
                ## RESPONSE ATTRIBUTES
                ## ----------------------------------------------

                # The relative timestamp of when the server returned the response (in seconds)
                'resp_time':        float,
                # Response payload (list of BSON objs)
                'resp_content':     list,
                # Response payload size [bytes]
                'resp_size':        int,
                # Unique identifier of the response packet
                'resp_id':          int,

                ## ----------------------------------------------
                ## INTERNAL DATA
                ## ----------------------------------------------
                
                # A mapping from keys to their predicate types
                'predicates':       dict,
            }
        ],
    }
    required_fields = [
        'session_id', 'ip_client', 'ip_server',
        # 'operations.collection', 'operations.type'
    ]
    indexes = [
        {
            'fields': ['session_id'],
            'unique': True,
        },
    ]
    default_values = {
        'operations': [ ],
    }

    @staticmethod
    def operationFactory():
        """Return an uninitialized operation dict that can then be inserted into this Session"""
        op = { }
        for k,v in Session.structure['operations'][-1].iteritems():
            if v in [list, dict]:
                op[k] = v()
            else:
                op[k] = None
        ## FOR
        return (op)
    ## DEF

## CLASS