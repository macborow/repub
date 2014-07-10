repub.py
========

repub.py extracts text from websites to EPUB files, i.e. lets you save articles for reading on the go. Produces lightweight documents with no images, etc.

It is really very simple - written in one afternoon after I got a bit frustrated with existing online converters.

Requirements
============

 - Python 2.7
 - BeautifulSoup (http://www.crummy.com/software/BeautifulSoup/).

Usage
=====

The following command line switches are supported:
```
  -h, --help  show this help message and exit
  -f F        path to input file
  -u U        URL to input file
  -o O        output directory (working directory used if not provided)
  -d          debug mode
  -v          verbose
```

License
=======

The MIT License (MIT)

Copyright (c) 2014 Maciej Borowik

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

