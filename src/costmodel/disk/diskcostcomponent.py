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
import os
import sys
import math
import logging
from pprint import pformat

# mongodb-d4
import workload

basedir = os.path.realpath(os.path.dirname(__file__))
sys.path.append(os.path.join(basedir, "../"))

import catalog
from costmodel import AbstractCostComponent
from fastlrubuffer import FastLRUBuffer
from fastlrubufferusingwindow import FastLRUBufferWithWindow
from workload import Session
from util import Histogram, constants

LOG = logging.getLogger(__name__)

## ==============================================
## Disk Cost
## ==============================================

class DiskCostComponent(AbstractCostComponent):

    def __init__(self, state):
        AbstractCostComponent.__init__(self, state)
        self.debug = False

        self.buffers = [ ]
        for i in xrange(self.state.num_nodes):
            lru = FastLRUBufferWithWindow(self.state.window_size)
            self.buffers.append(lru)
    ## DEF

    
    def reset(self):
        for buf in self.buffers:
            buf.reset()
            
    def getCostImpl(self, design):
        """
            Estimate the Disk Cost for a design and a workload
            Note: If this is being invoked with overallCost(), then the diskCost()
            should be calculated before skewCost() because we will reused the same
            histogram of how often nodes are touched in the workload
        """
        # delta = self.__getDelta__(design)

        # Initialize all of the LRU buffers
        # since every lru has the same configuration, we can cache the first initialization then deepcopy it to other
        #    lrus
        cache = None
        # for lru in self.buffers:
        #     cache = lru.initialize(design, delta, cache)
        #     LOG.info(lru)
        #     lru.validate()

        # Ok strap on your helmet, this is the magical part of the whole thing!
        #
        # Outline:
        # + For each operation, we need to figure out what document(s) it's going
        #   to need to touch. From this we want to compute a unique hash signature
        #   for those document so that we can identify what node those documents
        #   reside on and whether those documents are in our working set memory.
        #
        # + For each node, we are going to have a single LRU buffer that simulates
        #   the working set for all collections and indexes in the database.
        #   Documents entries are going to be tagged based on whether they are
        #   part of an index or a collection.
        #
        # + Now when we iterate through each operation in our workload, we are
        #   going to need to first figure out what index (if any) it will need
        #   to use and how it will be used (i.e., equality look-up or range scan).
        #   We can then compute the hash for the look-up keys.
        #   If that key is in the LRU buffer, then we will update its entry's last
        #   accessed timestamp. If it's not, then we will increase the page hit
        #   counter and evict some other entry.
        #   After evaluating the target index, we will check whether the index
        #   covers the query. If it does, then we're done
        #   If not, then we need to compute hash for the "base" documents that it
        #   wants to access (i.e., in the collection). Then just as before, we
        #   will check whether its in our buffer, make an eviction if not, and
        #   update our page hit counter.
        #   There are several additional corner cases that we need to handle:
        #      INSERT/UPDATE: Check whether it's an upsert query
        #      INSERT/UPDATE/DELETE: We assume that they're using a WAL and therefore
        #                            writing dirty pages is "free"
        #      UPDATE/DELETE: Check whether the "multi" flag is set to true, which will
        #                     tell us to stop the scan after the first matching document
        #                     is found.
        #
        # NOTE: We don't need to keep track of evicted tuples. It's either in the LRU buffer or not.
        # TODO: We may want to figure out how to estimate whether we are traversing
        #       indexes on the right-hand side of the tree. We could some preserve
        #       the sort order the keys when we hash them...

        # Worst case is when every query requires a full collection scan
        # Best case, every query is satisfied by main memory
        totalWorst = 0
        totalCost = 0
        sess_ctr = 0
        
        for sess in self.state.workload:
            for op in sess['operations']:
                # is the collection in the design - if not ignore
                if not design.hasCollection(op['collection']):
                    if self.debug: LOG.debug("NOT in design: SKIP - All operations on %s", col_name)
                    continue
                if design.isRelaxed(op['collection']):
                    if self.debug: LOG.debug("NOT in design: SKIP - All operations on %s", col_name)
                    continue
                col_info = self.state.collections[op['collection']]

                # Initialize cache if necessary
                # We will always want to do this regardless of whether caching is enabled
                cache = self.state.getCacheHandle(col_info)

                # Check whether we have a cache index selection based on query_hashes
                indexKeys, covering = cache.best_index.get(op["query_hash"], (None, None))
                if indexKeys is None:
                    indexKeys, covering = self.guessIndex(design, op)
                    if self.state.cache_enable:
                        if self.debug: self.state.cache_miss_ctr.put("best_index")
                        cache.best_index[op["query_hash"]] = (indexKeys, covering)
                elif self.debug:
                    self.state.cache_hit_ctr.put("best_index")
                pageHits = 0
                maxHits = 0
                isRegex = self.state.__getIsOpRegex__(cache, op)
                # Grab all of the query contents
                for content in workload.getOpContents(op):
                    for node_id in self.state.__getNodeIds__(cache, design, op):
                        lru = self.buffers[node_id]

                        # TODO: Need to handle whether it's a scan or an equality predicate
                        # TODO: We need to handle when we have a regex predicate. These are tricky
                        #       because they may use an index that will examine all a subset of collections
                        #       and then execute a regex on just those documents.

                        # If we have a target index, hit that up
                        if indexKeys and not isRegex: # FIXME
                            documentId = cache.index_docIds.get(op['query_id'], None)
                            if documentId is None:
                                values = catalog.getFieldValues(indexKeys, content)
                                try:
                                    documentId = hash(values)
                                except:
                                    LOG.error("Failed to compute index documentIds for op #%d - %s\n%s",\
                                        op['query_id'], values, pformat(op))
                                    raise
                                if self.state.cache_enable:
                                    if self.debug: self.state.cache_miss_ctr.put("index_docIds")
                                    cache.index_docIds[op['query_id']] = documentId
                            elif self.debug:
                                self.state.cache_hit_ctr.put("index_docIds")
                                ## IF
                            hits = lru.getDocumentFromIndex(indexKeys, documentId)
                            # print "hits: ", hits
                            pageHits += hits
                            maxHits += hits if op['type'] == constants.OP_TYPE_INSERT else cache.fullscan_pages
                            if self.debug:
                                LOG.debug("Node #%02d: Estimated %d index scan pageHits for op #%d on %s.%s",\
                                    node_id, hits, op["query_id"], op["collection"], indexKeys)

                        # If we don't have an index, then we know that it's a full scan because the
                        # collections are unordered
                        if not indexKeys:
                            if self.debug:
                                LOG.debug("No index available for op #%d. Will have to do full scan on '%s'",\
                                    op["query_id"], op["collection"])
                            pageHits += cache.fullscan_pages
                            maxHits += cache.fullscan_pages

                        # Otherwise, if it's not a covering index, then we need to hit up
                        # the collection to retrieve the whole document
                        elif not covering:
                            documentId = cache.collection_docIds.get(op['query_id'], None)
                            if documentId is None:
                                values = catalog.getAllValues(content)
                                try:
                                    documentId = hash(values)
                                except:
                                    LOG.error("Failed to compute collection documentIds for op #%d - %s\n%s",\
                                        op['query_id'], values, pformat(op))
                                    raise
                                if self.state.cache_enable:
                                    if self.debug: self.state.cache_miss_ctr.put("collection_docIds")
                                    cache.collection_docIds[op['query_id']] = documentId
                            elif self.debug:
                                self.state.cache_hit_ctr.put("collection_docIds")
                                ## IF
                            hits = lru.getDocumentFromCollection(op['collection'], documentId)
                            pageHits += hits
                            maxHits += hits if op['type'] == constants.OP_TYPE_INSERT else cache.fullscan_pages
                            if self.debug:
                                LOG.debug("Node #%02d: Estimated %d collection scan pageHits for op #%d on %s",\
                                    node_id, hits, op["query_id"], op["collection"])
                        
                        # We have a covering index, which means that we don't have
                        # to do a look-up on the document in the collection.
                        # But we still need to increase maxHits so that the final
                        # ratio is counted correctly
                        # Yang seems happy with this...
                        else:
                            assert op['type'] != constants.OP_TYPE_INSERT
                            maxHits += cache.fullscan_pages
                    ## FOR (node)
                ## FOR (content)

                totalCost += pageHits
                totalWorst += maxHits
                if self.debug:
                    LOG.debug("Op #%d on '%s' -> [pageHits:%d / worst:%d]",\
                        op["query_id"], op["collection"], pageHits, maxHits)
                assert pageHits <= maxHits,\
                    "Estimated pageHits [%d] is greater than worst [%d] for op #%d\n%s" %\
                    (pageHits, maxHits, op["query_id"], pformat(op))
                ## FOR (op)
            sess_ctr += 1

            ## FOR (sess)

        # The final disk cost is the ratio of our estimated disk access cost divided
        # by the worst possible cost for this design. If we don't have a worst case,
        # then the cost is simply zero
        assert totalCost <= totalWorst,\
            "Estimated total pageHits [%d] is greater than worst case pageHits [%d]" % (totalCost, totalWorst)
        final_cost = float(totalCost) / float(totalWorst) if totalWorst else 0
        evicted = sum([ lru.evicted for lru in self.buffers ])
        LOG.info("Computed Disk Cost: %s [pageHits=%d / worstCase=%d / evicted=%d]",\
                 final_cost, totalCost, totalWorst, evicted)
        
        return final_cost
    ## DEF

    def finish(self):
        buffer_total = sum([ lru.window_size for lru in self.buffers ])
        buffer_remaining = sum([ lru.free_slots for lru in self.buffers ])
        buffer_ratio = (buffer_total - buffer_remaining) / float(buffer_total)

        map(FastLRUBufferWithWindow.validate, self.buffers)

        if self.debug:
            cache_success = sum([ x for x in self.state.cache_hit_ctr.itervalues() ])
            cache_miss = sum([ x for x in self.state.cache_miss_ctr.itervalues() ])
            cache_ratio = cache_success / float(cache_success + cache_miss)
            LOG.debug("Internal Cache Ratio %.2f%% [total=%d]", cache_ratio*100, (cache_miss+cache_success))
            LOG.debug("Cache Hits [%d]:\n%s", cache_success, self.state.cache_hit_ctr)
            LOG.debug("Cache Misses [%d]:\n%s", cache_miss, self.state.cache_miss_ctr)
            LOG.debug("-"*100)
            LOG.debug("Buffer Usage %.2f%% [total=%d / used=%d]",buffer_ratio*100, buffer_total, (buffer_total - buffer_remaining))
    ## DEF

    def reset(self):
        for lru in self.buffers:
            lru.reset()
    ## DEF

    def guessIndex(self, design, op):
        """
            Return a tuple containing the best index to use for this operation and a boolean
            flag that is true if that index covers the entire operation's query
        """
        # Simply choose the index that has most of the fields
        # referenced in the operation.
        indexes = design.getIndexes(op['collection'])
        op_contents = workload.getOpContents(op)
        # extract the keys from op_contents
        op_index_list = []
        for query in op_contents:
            for key in query.iterkeys():
                op_index_list.append(key)
        # add the projection keys into op_index_set
        # The op["query_fileds"] is the projection
        projectionFields = op['query_fields']

        if projectionFields:
            for key in projectionFields.iterkeys():
                op_index_list.append(key)
            
        best_index = None
        best_ratio = None
        for i in xrange(len(indexes)):
            field_cnt = 0
            for indexKey in indexes[i]:
                indexMatch = (indexKey in op_index_list)
                # We can't use a field if it's being used in a regex operation
                if indexMatch and not workload.isOpRegex(op, field=indexKey):
                    field_cnt += 1
                
                if not indexMatch or field_cnt >= len(op_index_list):
                    break
            field_ratio = field_cnt / float(len(indexes[i]))
            if not best_index or field_ratio >= best_ratio:
                # If the ratios are the same, then choose the
                # one with the most keys
                if field_ratio == best_ratio:
                    if len(indexes[i]) < len(best_index):
                        continue
                
                if field_ratio != 0:
                    best_index = indexes[i]
                    best_ratio = field_ratio
            ## FOR
        if self.debug:
            LOG.debug("Op #%d - BestIndex:%s / BestRatio:%s",\
                op['query_id'], best_index, best_ratio)

        # Check whether this is a covering index
        covering = False
        if best_index and op['type'] == constants.OP_TYPE_QUERY:
            # Extract the indexes from best_index
            best_index_list = []
            for index in best_index:
                best_index_list.append(index)
            
            if len(op_index_list) <= len(best_index_list):
                counter = 0
                while counter < len(op_index_list):
                    if op_index_list[counter] != best_index_list[counter]:
                        break
                    counter += 1
                        
                if counter == len(op_index_list):
                    covering = True
            ## IF

        return best_index, covering
    ## DEF

## CLASS
