# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
# Copyright (C) 2012 by Brown University
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
# -----------------------------------------------------------------------
import logging
import math
from pprint import pformat

import catalog
from util.histogram import Histogram
import workload
from util import constants

LOG = logging.getLogger(__name__)

class NodeEstimator(object):

    def __init__(self, collections, num_nodes):
        assert isinstance(collections, dict)
#        LOG.setLevel(logging.DEBUG)
        self.debug = LOG.isEnabledFor(logging.DEBUG)
        self.collections = collections
        self.num_nodes = num_nodes

        # Keep track of how many times that we accessed each node
        self.nodeCounts = Histogram()
        self.op_count = 0
    ## DEF

    def reset(self):
        """
            Reset internal counters for this estimator.
            This should be called everytime we start evaluating a new design
        """
        self.nodeCounts.clear()
        self.op_count = 0
    ## DEF

    def estimateNodes(self, design, op):
        """
            For the given operation and a design object,
            return an estimate of a list of node ids that we think that
            the query will be executed on
        """
        results = set()
        broadcast = True
        shardingKeys = design.getShardKeys(op['collection'])

        if self.debug:
            LOG.debug("Computing node estimate for Op #%d [sharding=%s]", \
                      op['query_id'], shardingKeys)

        # If there are no sharding keys
        # All requests on this collection will be routed to the primary node
        # We assume the node 0 is the primary node
        if len(shardingKeys) == 0:
            broadcast = False
            results.add(0)

        # Inserts always go to a single node
        elif op['type'] == constants.OP_TYPE_INSERT:
            # Get the documents that they're trying to insert and then
            # compute their hashes based on the sharding key
            # Because there is no logical replication, each document will
            # be inserted in one and only one node
            for content in workload.getOpContents(op):
                values = catalog.getFieldValues(shardingKeys, content)
                results.add(self.computeTouchedNode(op['collection'], shardingKeys, values))
            ## FOR
            broadcast = False

        # Network costs of SELECT, UPDATE, DELETE queries are based off
        # of using the sharding key in the predicate
        elif len(op['predicates']) > 0:
            predicate_fields = set()
            predicate_types = set()
            for k,v in op['predicates'].iteritems() :
                if design.inShardKeyPattern(op['collection'], k):
                    predicate_fields.add(k)
                    predicate_types.add(v)
            if len(predicate_fields) == len(shardingKeys):
                broadcast = False
            if self.debug:
                LOG.debug("Op #%d %s Predicates: %s [broadcast=%s / predicateTypes=%s]",\
                          op['query_id'], op['collection'], op['predicates'], broadcast, list(predicate_types))

            ## ----------------------------------------------
            ## PRED_TYPE_REGEX
            ## ----------------------------------------------
            if not broadcast and constants.PRED_TYPE_REGEX in predicate_types:
                # Any query that is using a regex on the sharding key must be broadcast to every node
                # It's not complete accurate but it's just easier that way
                broadcast = True

            ## ----------------------------------------------
            ## PRED_TYPE_RANGE
            ## ----------------------------------------------
            elif not broadcast and constants.PRED_TYPE_RANGE in predicate_types:
                broadcast = True
            ## ----------------------------------------------
            ## PRED_TYPE_EQUALITY
            ## ----------------------------------------------
            elif not broadcast and constants.PRED_TYPE_EQUALITY in predicate_types:
                broadcast = False
                for content in workload.getOpContents(op):
                    values = catalog.getFieldValues(shardingKeys, content)
                    results.add(self.computeTouchedNode(op['collection'], shardingKeys, values))
                ## FOR
            ## ----------------------------------------------
            ## BUSTED!
            ## ----------------------------------------------
            elif not broadcast:
                raise Exception("Unexpected predicate types '%s' for op #%d" % (list(predicate_types), op['query_id']))
        ## IF

        if broadcast:
            if self.debug: LOG.debug("Op #%d on '%s' is a broadcast query to all nodes",\
                                     op["query_id"], op["collection"])
            map(results.add, xrange(0, self.num_nodes[op["collection"]]))

        map(self.nodeCounts.put, results)
        self.op_count += 1
        return results
    ## DEF

    def computeTouchedNode(self, col_name, fields, values):
        index = 0
        factor = 1
        if len(values) != len(fields):
            return 0
        for i in range(len(fields)):
            index += (self.computeTouchedRange(col_name, fields[i], values[i]) * factor)
            factor *= self.num_nodes[col_name]
        return index / int(math.pow(self.num_nodes[col_name], len(fields) - 1))

    ## DEF

    def computeTouchedRange(self, col_name, field_name, value):
        ranges = self.collections[col_name]['fields'][field_name]['ranges']
        if len(ranges) == 0:
            return hash(str(value)) % self.num_nodes[col_name]
        index = 0
        while index < len(ranges):
            if index == len(ranges) - 1:
                return index % self.num_nodes[col_name]
            if ranges[index] <= value < ranges[index + 1]:
                return index % self.num_nodes[col_name]
            index += 1
        return index % self.num_nodes[col_name]

    def guessNodes(self, design, colName, fieldName):
        """
            Return the number of nodes that a query accessing a collection
            using the given field will touch.
            This serves as a stand-in for the EXPLAIN function referenced in the paper
        """
        col_info = self.collections[colName]
        if not fieldName in col_info['fields']:
            raise Exception("Invalid field '%s.%s" % (colName, fieldName))
        field = col_info['fields'][fieldName]

        # TODO: How do we use the statistics to determine the selectivity of this particular
        #       attribute and thus determine the number of nodes required to answer the query?
        return int(math.ceil(field['selectivity'] * self.num_nodes[colName]))
    ## DEF

    def getOpCount(self):
        """Return the number of operations evaluated"""
        return self.op_count
## CLASS