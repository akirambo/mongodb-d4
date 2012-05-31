#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import division
import workload
import datetime
import costmodel
import search

## ==============================================
## main
## ==============================================

if __name__ == '__main__':

    config = {
        'alpha' : 1.0,
        'beta' : 1.0,
        'gamma' : 1.0,
        'nodes' : 4,
        'max_memory' : 512,
        'address_size' : 64,
        'skew_intervals' : 10,
    }
    
    statistics = {
        'A' : {
            'fields' : {
                'col1' : {
                    'query_use_count' : 1000,
                    'cardinality' : 500,
                    'selectivity' : 0.5,
                },
                'col2' : {
                    'query_use_count' : 1000,
                    'cardinality' : 100,
                    'selectivity' : 1.0,
                },
                'col3' : {
                    'query_use_count' : 1000,
                    'cardinality' : 250,
                    'selectivity' : 0.25,
                },
                'col4' : {
                    'query_use_count' : 500,
                    'cardinality' : 100,
                    'selectivity' : 1.0,
                },
                'col5' : {
                    'query_use_count' : 500,
                    'cardinality' : 100,
                    'selectivity' : 1.0,
                },
            },
            'tuple_count' : 100000,
            'workload_queries' : 1000,
            'workload_percent' : 0.05,
            'avg_doc_size' : 100,
            'max_pages' : 50,
        },
        'B' : {
            'fields' : {
                'col1' : {
                    'query_use_count' : 1000,
                    'cardinality' : 500,
                    'selectivity' : 0.5,
                },
                'col2' : {
                    'query_use_count' : 1000,
                    'cardinality' : 100,
                    'selectivity' : 1.0,
                },
                'col3' : {
                    'query_use_count' : 1000,
                    'cardinality' : 250,
                    'selectivity' : 0.25,
                },
                'col4' : {
                    'query_use_count' : 500,
                    'cardinality' : 100,
                    'selectivity' : 1.0,
                },
                'col5' : {
                    'query_use_count' : 500,
                    'cardinality' : 100,
                    'selectivity' : 1.0,
                },
            },
            'tuple_count' : 1000000,
            'workload_queries' : 1000,
            'workload_percent' : 0.95,
            'avg_doc_size' : 2000,
            'max_pages' : 50,
        },
        'total_queries' : 1000,
    }

    ## ----------------------------------------------
    ## STEP 1
    ## Network Cost Evaluation
    ## ----------------------------------------------
    print ''
    print 'Evaluating Network Cost'
    
    wk = workload.Workload()
    sess = workload.SyntheticSession()
    sess.startTime = 0
    sess.endTime = 1000
    ts = 0
    for i in range(0, 1000) :
        q = workload.Query()
        q.collection = 'A'
        q.type = 'select'
        if i % 2 == 1 :
            q.predicates = {'col1' : 'equality', 'col2' : 'equality', 'col3' : 'range'}
        else :
            q.predicates = {'col1' : 'equality', 'col2' : 'range', 'col3' : 'range', 'col4' : 'range'}
        q.projection = {}
        q.timestamp = ts + i
        sess.queries.append(q)
    wk.addSession(sess)
    
    cm = costmodel.CostModel(wk, config, statistics)
    
    print '** TEST 1: All ops executed at 1 shard '
    d1 = search.Design()
    d1.addCollection('A')
    d1.addShardKey('A', ['col1'])
    d1.addCollection('B')
    d1.addIndex('A', ['col1', 'col2'])
    d1.addIndex('B', ['col1'])
    d1.addIndex('B', ['col2'])
    d1.addIndex('B', ['col3'])
    print cm.networkCost(d1)
    
    print '** TEST 2: All ops executed at 2 shards '
    d2 = search.Design()
    d2.addCollection('A')
    d2.addShardKey('A', ['col2'])
    d2.addCollection('B')
    print cm.networkCost(d2)
    
    print '** TEST 3: All ops executed at 2 shards '
    d3 = search.Design()
    d3.addCollection('A')
    d3.addShardKey('A', ['col3'])
    d3.addCollection('B')
    print cm.networkCost(d3)
    
    print '** TEST 4: All ops executed at 2 shards '
    d4 = search.Design()
    d4.addCollection('A')
    d4.addShardKey('A', ['col4'])
    d4.addCollection('B')
    print cm.networkCost(d4)
    
    print '** TEST 5: All ops executed at 4 shards '
    d5 = search.Design()
    d5.addCollection('A')
    d5.addShardKey('A', ['col5'])
    d5.addCollection('B')
    d5.addIndex('B', ['col1'])
    d5.addIndex('B', ['col2'])
    
    print cm.networkCost(d5)
    
    ## ----------------------------------------------
    ## STEP 2
    ## Skew Cost Evaluation
    ## ----------------------------------------------
    
    print ''
    print 'Evaluating Skew Cost'
    
    print '** TEST 1: All ops executed at 1 shard'
    print cm.skewCost(d1)
    
    print '** TEST 2: All ops executed at 4 shards'
    print cm.skewCost(d5)
     
    ## -------------------------------------------------
    ## STEP 3
    ## Disk Cost evaluation
    ## -------------------------------------------------
    
    print ''
    print 'Evaluating Disk Cost'
    
    print '** Test 1:'
    print cm.diskCost(d1)
    
    #print '** Test 2:'
    #print cm.diskCost(d2)
    
    #print '** Test 3:'
    #print cm.diskCost(d3)
    
    #print '** Test 4:'
    #print cm.diskCost(d4)
    
    print '** Test 5:'
    print cm.diskCost(d5)
## MAIN