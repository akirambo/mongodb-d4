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

import random
import logging
import numpy
import math
from pprint import pformat

import catalog
from util import constants
from util.histogram import Histogram
from workload import OpHasher
import workload

LOG = logging.getLogger(__name__)

## ==============================================
## Abstract Convertor
## ==============================================
class AbstractConverter():
    def __init__(self, metadata_db, dataset_db):
        self.metadata_db = metadata_db
        self.dataset_db = dataset_db
        self.stop_on_error = False
        self.limit = None
        self.skip = None
        self.clean = None
        self.no_load = False
        self.no_reconstruct = False
        self.no_sessionizer = False

        self.total_ops = 0
        self.hasher = OpHasher()

        self.debug = LOG.isEnabledFor(logging.DEBUG)
    ## DEF

    def reset(self):
        # FIXME: This should be done with a single update query
        for col_info in self.metadata_db.Collection.fetch():
            for k,v in catalog.Collection.default_values.iteritems():
                if type(v) in [list, dict]: continue
                col_info[k] = v
            ## FOR

            ## TODO: This needs to be recursive
            for k, v in col_info['fields'].iteritems() :
                v['query_use_count'] = 0
                v['query_hash']  = 0
                v['cardinality'] = 0
                v['selectivity'] = 0.0
                v['avg_size']    = 0
            col_info.save()
        ## FOR
    ## DEF

    def process(self, no_load=False, no_post_process=False, page_size=constants.DEFAULT_PAGE_SIZE):
        if not no_load: self.loadImpl()
        #self.printAllSessionsTime()
        if not no_post_process: self.postProcess(page_size)
        # self.printAllCollectionInfo()
    ## DEF

    def loadImpl(self):
        raise NotImplementedError("Unimplemented %s.loadImpl()" % self.__init__.im_class)
    ## DEF

    def printAllSessionsTime(self):
        for sess in self.metadata_db.Session.fetch():
            print "start_time: %s", pformat(sess['start_time'])
            print "end_time: %s", pformat(sess['end_time'])
        ## FOR
        exit("CUPCAKE")
    ## DEF
    
    def printAllOperations(self):
        for sess in self.metadata_db.Session.fetch():
            for op in sess['operations']:
                print "ops\n%s", pformat(op)
            ## FOR
        ## FOR
        exit("CUPCAKE")
    ## DEF
    
    def printAllDocs(self):
        for col_name in self.dataset_db.collection_names():
            for doc in self.dataset_db[col_name].find():
                print "col_name: ", col_name
                print "doc\n", pformat(doc)
            ## FOR
        ## FOR
        exit("CUPCAKE")
    ## DEF

    def countDocs(self):
        counter = 0
        for colName in self.dataset_db.collection_names():
            for doc in self.dataset_db[colName].find():
                counter += 1
            ## FOR
        ## FOR
        print "doc count: ", counter
    ## DEF
    
    def printAllCollectionInfo(self):
        for colName in self.dataset_db.collection_names():
            # Skip ignored collections
            if colName.split(".")[0] in constants.IGNORED_COLLECTIONS:
                continue
            col_info = self.metadata_db.Collection.one({'name': colName})
            print "col_name: ", col_info['name']
            print "col_info\n", pformat(col_info)
        ## FOR
        exit("CUPCAKE")
    ## DEF

    def postProcess(self, page_size=constants.DEFAULT_PAGE_SIZE):
        """
            The PostProcessor performs final calculations on an already loaded metadata
            and workload database. These calculations can be computed regardless of whether
            the catalog information came from MongoSniff or MySQL.
            This should only be invoked once after do the initial loading.
        """
        # STEP 1: Add query hashes
        self.addQueryHashes()

        # STEP 2: Process workload
        self.computeWorkloadStats()

        # STEP 3: Process dataset
        self.extractSchemaCatalog()

        # Finalize workload percentage statistics for each collection
        percent_total = 0.0
        for col_info in self.metadata_db.Collection.find():
            for k in ['doc_count', 'workload_queries', 'avg_doc_size']:
                assert not col_info[k] is None, "%s.%s == None"  % (col_info['name'], k)
            col_info['workload_percent'] = col_info['workload_queries'] / float(self.total_ops)
            percent_total += col_info['workload_percent']

            col_info['max_pages'] = min(1, col_info['doc_count'] * col_info['avg_doc_size'] / page_size)
            col_info.save()
        ## FOR
        assert round(percent_total, 1) > 0.0 and round(percent_total, 1) <= 1.0,\
            "Invalid workload percent total %f [totalOps=%d]" % (percent_total, self.total_ops)
    ## DEF

    def addQueryHashes(self):
        total = self.metadata_db.Session.find().count()
        LOG.info("Adding query hashes to %d sessions" % total)
        invalid_sess = [ ]
        for sess in self.metadata_db.Session.fetch():
            # It is possible that the query content of some operations, which will
            # cause sess.save() to fail. To work this around, we just delete the incomplete op
            # from the session
            for i in xrange(len(sess['operations']) - 1, - 1, -1):
                op = sess['operations'][i]
                # For some reason even though the hash is an int, it
                # gets converted into a long when it shows up in MongoDB
                # I don't know why and frankly, I don't really care
                # So we'll just cast everything to a long and make sure that
                # the Session schema expects it to be a long
                try:
                    op["query_hash"] = long(self.hasher.hash(op))
                    if self.debug:
                        LOG.debug("  %d.%d -> Hash:%d", sess["session_id"], op["query_id"], op["query_hash"])
                except Exception:
                    sess['operations'].remove(op)
                ## TRY
            try:
                sess.save()
            except Exception:
                if self.debug:
                    LOG.info("session can not be saved due to operations error. Dump:\n%s", sess['operations'])
                sess.delete()
            if self.debug: LOG.debug("Updated Session #%d", sess["session_id"])
        ## FOR
        if self.debug:
            LOG.debug("Query Class Histogram:\n%s" % self.hasher.histogram)
        ## IF
    ## DEF

    def computeWorkloadStats(self):
        """Process Workload Trace"""
        LOG.info("Computing database statistics from workload trace")

        # We'll maintain a local cache of Collection objects so that
        # we only have to look-up/create each one once, and then we can
        # save them all together at the end
        collectionCache = { }
        for sess in self.metadata_db.Session.fetch():
            start_time = None
            end_time = None

            for op in sess['operations']:
                # We need to know the total number of queries that we've seen
                self.total_ops += 1

                # The start_time is the timestamp of when the first query occurs
                if not start_time: start_time = op['query_time']
                start_time = min(start_time, op['query_time'])

                # The end_time is the timestamp of when the last response arrives
                if 'resp_time' in op and op['resp_time']:
                    end_time = max(end_time, op['resp_time'])
                elif not end_time and op['query_time']:
                    end_time = op['query_time']

                # Get the collection information object
                # We will use this to store the number times each key is referenced in a query
                if not op['collection'] in collectionCache:
                    if op['collection'] in constants.IGNORED_COLLECTIONS or op['collection'].endswith("$cmd"):
                        continue
                    col_info = self.metadata_db.Collection.one({'name': op['collection']})
                    if not col_info:
                        col_info = self.metadata_db.Collection()
                        col_info['name'] = op['collection']
                    collectionCache[op['collection']] = col_info
                    col_info['workload_queries'] = 0

                col_info = collectionCache[op['collection']]
                col_info['workload_queries'] += 1

                if not 'predicates' in op or not op['predicates']:
                    op['predicates'] = { }

                try:
                    for content in workload.getOpContents(op):
                        self.processOpFields(col_info['fields'], op, content)
                except:
                    LOG.error("Unexpected error for operation #%d in Session #%d\n%s", \
                              op['query_id'], sess['session_id'], pformat(op))
                    raise
            ## FOR (operations)

            if start_time and end_time:
                sess['start_time'] = start_time
                sess['end_time'] = end_time

            if self.debug: LOG.debug("Updating Session #%d" % sess['session_id'])
            try:
                sess.save()
            except:
                LOG.error("Failed to update Session #%d", sess['session_id'])
                raise
        ## FOR (sessions)

        # Save off all our skanky stink boxes right here...
        for col_info in collectionCache.itervalues():
            col_info.save()

    ## DEF

    def processOpFields(self, fields, op, content):
        if self.debug: LOG.debug("Processing operation fields\n%s", pformat(content))
        for k,v in content.iteritems():
            # Skip anything that starts with our special char
            # Those are flag markers used by MongoDB's queries
            if k.startswith(constants.REPLACE_KEY_DOLLAR_PREFIX):
                continue

            # We need to add the field to the collection if it doesn't
            # already exist. This will occur if this op was an aggregate,
            # which we ignore when recreating the schema
            f_type = type(v)
            if not k in fields:
                fields[k] = catalog.Collection.fieldFactory(k, catalog.fieldTypeToString(f_type))
            fields[k]['query_use_count'] += 1

            # No predicate for insert operations
            # No projections for insert operations
            if op['type'] != constants.OP_TYPE_INSERT:
                # Update how this key was used with predicates
                if workload.isOpRegex(op, field=k):
                    op['predicates'][k] = constants.PRED_TYPE_REGEX
                elif isinstance(v, dict):
                    op['predicates'][k] = constants.PRED_TYPE_RANGE
                elif not k in op['predicates']:
                    op['predicates'][k] = constants.PRED_TYPE_EQUALITY

            ## TODO: Should we expect there to be field names with dot notation here?
            ##       Or should have all been cleaned out by the converters?

        ## FOR

        return
    ## DEF

    ## ==============================================
    ## SCHEMA EXTRACTION
    ## ==============================================

    def extractSchemaCatalog(self, sample_rate = 100):
        """
            Iterates through all documents and infers the schema.
            This only needs to extract the schema skeleton. The
            post-processing stuff in the AbstractConverter will populate
            the statistics information for each collection
        """
        LOG.info("Extracting database schema catalog from workload trace")
        for colName in self.dataset_db.collection_names():
            # Skip ignored collections
            if colName.split(".")[0] in constants.IGNORED_COLLECTIONS:
                continue
            LOG.info("Extracting schema catalog information from collection '%s'", colName)

            # Get the collection information object
            # We will use this to store the number times each key is referenced in a query
            col_info = self.metadata_db.Collection.one({'name': colName})
            if not col_info:
                col_info = self.metadata_db.Collection()
                col_info['name'] = colName

            col_info['doc_count'] = 0
            col_info['data_size'] = 0l

            # Examine each document in the dataset for this collection
            for doc in self.dataset_db[colName].find():
                col_info['doc_count'] += 1
                if random.randint(0, 100) <= sample_rate:
                    try:
                        self.processDataFields(col_info, col_info['fields'], doc)
                    except:
                        msg = "Unexpected error when processing '%s' data fields" % colName
                        msg += "\n" + pformat(doc)
                        LOG.error(msg)
                        raise
            ## FOR

            # Calculate average tuple size (if we have at least one)
            if not col_info['doc_count']:
                col_info['avg_doc_size'] = int(col_info['data_size'])
            else :
                col_info['avg_doc_size'] = int(col_info['data_size'] / col_info['doc_count'])

            # Calculate cardinality and selectivity
            self.computeFieldStats(col_info, col_info['fields'])

            if self.debug:
                LOG.debug("Saved new catalog entry for collection '%s'" % colName)
            try:
                col_info.save()
            except Exception:
                if self.debug:
                    LOG.info("abnormal col_info\n%s", pformat(col_info))
                raise
        ## FOR
    ## DEF

    def processDataFields(self, col_info, fields, doc):
        """
            Recursively traverse a single document and extract out the field information
        """
        if self.debug: LOG.debug("Extracting fields for document:\n%s" % pformat(doc))

        # Check if the current doc has parent_col, but this will only apply to its fields
        parent_col = doc.get('parent_col', None)

        for k,v in doc.iteritems():
            # Skip if this is the _id field
            if constants.SKIP_MONGODB_ID_FIELD and k == '_id': continue
            if k == constants.FUNCTIONAL_FIELD: continue
            f_type = type(v)
            f_type_str = catalog.fieldTypeToString(f_type)

            if not k in fields:
                # This is only subset of what we will compute for each field
                # See catalog.Collection for more information
                if self.debug: LOG.debug("Creating new field entry for '%s'" % k)
                fields[k] = catalog.Collection.fieldFactory(k, f_type_str)
            else:
                fields[k]['type'] = f_type_str
                # Sanity check
                # This won't work if the data is not uniform
                #if v != None:
                #assert fields[k]['type'] == f_type_str, \
                #"Mismatched field types '%s' <> '%s' for '%s'" % (fields[k]['type'], f_type_str, k)

            # We will store the distinct values for each field in a set
            # that is embedded in the field. We will delete it when
            # we call computeFieldStats()
            if not 'distinct_values' in fields[k]:
                fields[k]['distinct_values'] = set()
            if not "num_values" in fields[k]:
                fields[k]['num_values'] = 0
            # Likewise, we will also store a histogram for the different sizes
            # of each field. We will use this later on to compute the weighted average
            if not 'size_histogram' in fields[k]:
                fields[k]['size_histogram'] = Histogram()
            # Maintain a histogram of list lengths
            if not 'list_len' in fields[k]:
                fields[k]['list_len'] = Histogram();
                
            if fields[k]['query_use_count'] > 0 and not k in col_info['interesting']:
                col_info['interesting'].append(k)

            ## ----------------------------------------------
            ## NESTED FIELDS
            ## ----------------------------------------------
            if isinstance(v, dict):
                # Check for a special data field
                if len(v) == 1 and v.keys()[0].startswith(constants.REPLACE_KEY_DOLLAR_PREFIX):
                    v = v[v.keys()[0]]
                    # HACK to handle lists (hopefully dict as well)from nested IN clauses...
                    all_values = v if isinstance(v, list) else [ v ]
                    for v in all_values:
                        if isinstance(v, dict):
                            v = v.values()[0]
                        
                        fields[k]['type'] = catalog.fieldTypeToString(type(v))
                        try:
                            size = catalog.getEstimatedSize(fields[k]['type'], v)
                        except:
                            LOG.error("Failed to estimate size for field '%s' in collection '%s'\n%s", \
                                    k, col_info['name'], pformat(fields[k]))
                            raise
                        col_info['data_size'] += size
                        fields[k]['size_histogram'].put(size)
                        fields[k]['distinct_values'].add(v)
                        fields[k]['num_values'] += 1
                        if parent_col:
                            fields[k]['parent_col'] = parent_col
                    ## FOR
                else:
                    if self.debug: LOG.debug("Extracting keys in nested field for '%s'" % k)
                    if not 'fields' in fields[k]: fields[k]['fields'] = { }
                    self.processDataFields(col_info, fields[k]['fields'], doc[k])

            ## ----------------------------------------------
            ## LIST OF VALUES
            ## Could be either scalars or dicts. If it's a dict, then we'll just
            ## store the nested field information in the 'fields' value
            ## If it's a list, then we'll use a special marker 'LIST_INNER_FIELD' to
            ## store the field information for the inner values.
            ## ----------------------------------------------
            elif isinstance(v, list):
                if self.debug: LOG.debug("Extracting keys in nested list for '%s'" % k)
                if not 'fields' in fields[k]: fields[k]['fields'] = { }

                list_len = len(doc[k])
                fields[k]['list_len'].put(list_len)
                for i in xrange(list_len):
                    inner_type = type(doc[k][i])
                    # More nested documents...
                    if inner_type == dict:
                        if self.debug: LOG.debug("Extracting keys in nested field in list position %d for '%s'" % (i, k))
                        self.processDataFields(col_info, fields[k]['fields'], doc[k][i])
                    else:
                        # TODO: We probably should store a list of types here in case
                        #       the list has different types of values
                        inner = fields[k]['fields'].get(constants.LIST_INNER_FIELD, {})
                        inner['type'] = catalog.fieldTypeToString(inner_type)
                        try:
                            inner_size = catalog.getEstimatedSize(inner['type'], doc[k][i])
                        except:
                            LOG.error("Failed to estimate size for list entry #%d for field '%s' in collection '%s'\n%s",\
                                      i, k, col_info['name'], pformat(fields[k]))
                            raise

                        fields[k]['fields'][constants.LIST_INNER_FIELD] = inner
                        fields[k]['size_histogram'].put(inner_size)
                        fields[k]['distinct_values'].add(doc[k][i])
                        fields[k]['num_values'] += 1
                        if parent_col:
                            fields[k]['parent_col'] = parent_col
                ## FOR (list)
            ## ----------------------------------------------
            ## SCALAR VALUES
            ## ----------------------------------------------
            else:
                try:
                    size = catalog.getEstimatedSize(fields[k]['type'], v)
                except:
                    LOG.error("Failed to estimate size for field %s in collection %s\n%s",\
                              k, col_info['name'], pformat(fields[k]))
                    raise
                col_info['data_size'] += size
                fields[k]['size_histogram'].put(size)
                fields[k]['distinct_values'].add(v)
                fields[k]['num_values'] += 1
                if parent_col:
                    fields[k]['parent_col'] = parent_col
        ## FOR
    ## DEF

    def computeFieldStats(self, col_info, fields):
        """
            Recursively calculate the cardinality of each field.
            This should only be invoked after processDataFields() has been called
        """
        for k,field in fields.iteritems():
            # Compute list information
            if 'list_len' in field:
                if len(field['list_len']) > 0:
                    all_values = field['list_len'].getAllValues()
                    field['list_len_min'] = int(min(all_values))
                    field['list_len_max'] = int(max(all_values))
                    field['list_len_avg'] = numpy.average(all_values)
                    field['list_len_stdev'] = numpy.average(all_values)
                del field['list_len']
            
            # Compute a weighted average for each field
            if 'size_histogram' in field:
                h = field['size_histogram']
                total = 0.0
                for size, count in h.iteritems():
                    if count: total += (size * count)
                num_samples = h.getSampleCount()
                if num_samples:
                    field['avg_size'] = int(math.ceil(total / num_samples))
                else:
                    field['avg_size'] = 0
                del field['size_histogram']
            # Use the distinct values set to determine cardinality + selectivity
            if 'distinct_values' in field:
#                print "*" * 20
#                print "col_name: ", col_info['name']
#                print "field: ", k
#                print "distinct values: ", pformat(field['distinct_values'])
                field['cardinality'] = len(field['distinct_values'])
                if field['num_values'] == 0:
                    field['selectivity'] = 0.0
                else :
                    field['selectivity'] = float(field['cardinality']) / field['num_values']
                del field['distinct_values']
                del field['num_values']
            if 'fields' in field and field['fields']:
                self.computeFieldStats(col_info, field['fields'])
        ## FOR
    ## DEF

    ## ==============================================
    ## OPERATION FIXIN'
    ## ==============================================

    def fixInvalidCollections(self):
        searchKey = {"operations.collection": constants.INVALID_COLLECTION_MARKER}
        for session in self.metadata_db.Session.find(searchKey):
            for op in session["operations"]:
                dirty = False
                if op["collection"] != constants.INVALID_COLLECTION_MARKER:
                    continue

                if self.debug: LOG.debug("Attempting to fix corrupted Operation:\n%s" % pformat(op))

                # For each field referenced in the query, build a histogram of
                # which collections have a field with the same name
                fields = workload.getReferencedFields(op)
                h = Histogram()
                for c in self.metadata_db.Collection.find():
                    for f in c['fields']:
                        if f in fields:
                            h.put(c['name'])
                    ## FOR
                ## FOR

                matches = h.getMaxCountKeys()
                if len(matches) == 0:
                    LOG.warn("No matching collection was found for corrupted operation\n%s" % pformat(op))
                    continue
                elif len(matches) > 1:
                    LOG.warn("More than one matching collection was found for corrupted operation %s\n%s" % (matches, pformat(op)))
                    continue
                else:
                    op["collection"] = matches[0]
                    dirty = True
                    self.fix_ctr += 1
                    LOG.info("Fix corrupted collection in operation\n%s" % pformat(op))
                    ## IF
                    ## FOR (operations)

            if dirty: session.save()
        ## FOR (sessions)

    ## DEF

## CLASS
