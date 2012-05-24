#!/usr/bin/env python
# -*- coding: utf-8 -*-



import unittest
from sanitizer import anonymize


def get_long_string(strings, iters):
    str = ""
    for i in range(iters):
        for s in strings:
            str += s
    #print str
    return str



class TestSanitizer (unittest.TestCase):
    
    def setUp(self):
        pass
    
    
    
    def testHashString(self):
    
        print("\n\n === Sanitizer Test === \n")
    
        # short strings
        short_string1 = get_long_string([' \\"hello\\" ', '\n\n \t\t \n\t \t\n', 'email: \\"emanuel@buzek.net\\"', '\'\'\'\'', "'\\\"'", "{inside: \\\"of a string\\\"}"], 1)
        short_string2 = get_long_string(['This is not a long string.  \n\n \t', '\n\t', '{\\"name\\"}', ' \\ END', '\\"string\\"', "'string'", "\\\"'quotes'\\\"", "open quotes: \\\" '"], 1)
        
        hash1 = anonymize.hash_string(short_string1, 0)
        hash2 = anonymize.hash_string(short_string2, 0)
        
        json = '{"key1" : "%s", "key2" : "%s"}' % (short_string1, short_string2)
        print json 
        
        expected_sanitized_json = '{"key1" : %s, "key2" : %s}' % (hash1, hash2)
        real_sanitized_json = anonymize.sanitize(json, 0)
        
        self.assertEqual(expected_sanitized_json, real_sanitized_json)
    
    
        # very very long strings
    
        long_string1 = get_long_string([' \\"hello\\" ', '\n\n \t\t \n\t \t\n', 'email: \\"emanuel@buzek.net\\"', '\'\'\'\'', "'\\\"'", "{inside: \\\"of a string\\\"}"], 5000)
        long_string2 = get_long_string(['This is a very string.  \n\n \t', '\n\t', '{\\"name\\"}', ' \\ END', '\\"string\\"', "'string'", "\\\"'quotes'\\\"", "open quotes: \\\" '"], 5000)
        
        hash1 = anonymize.hash_string(long_string1, 0)
        hash2 = anonymize.hash_string(long_string2, 0)
        
        long_json = '{"key1" : "%s", "key2" : "%s"}' % (long_string1, long_string2)
        
        expected_sanitized_long_json = '{"key1" : %s, "key2" : %s}' % (hash1, hash2)
        real_sanitized_long_json = anonymize.sanitize(long_json, 0)
        
        self.assertEqual(expected_sanitized_long_json, real_sanitized_long_json)
    
         
        # other tests
        
        str1 = "\"THIS SHOULD BE SIMPLY HASHED\""
        hash1 = anonymize.hash_string("THIS SHOULD BE SIMPLY HASHED", 0)
        result1 = anonymize.sanitize(str1, 0)
        self.assertEqual(hash1, result1)
        
        
        # many strings in json
        
        
        text = 'string with \\\"escaped quotes\\\"'
        hashed_text = anonymize.hash_string(text, 0)
        long_json = "{" + get_long_string(['"key" : "%s", ' % text], 4000) + "}"
        expected_result = "{" + get_long_string(['"key" : %s, ' % hashed_text], 4000) + "}"
        real_result = anonymize.sanitize(long_json, 0)
        
        #print long_json
        #print expected_result
        #print real_result
        
        self.assertEqual(expected_result, real_result)
        
        print "DONE"
        

## CLASS

if __name__ == '__main__':
    unittest.main()
## MAIN