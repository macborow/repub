"""
repub.py - extract text from websites to EPUB files.
Copyright (c) 2014, Maciej Borowik (https://github.com/macborow).
Released under MIT license (see bottom of the file)
"""
import sys
import os
import tempfile
import bs4
import argparse
import datetime
import logging
import uuid
import zipfile
import string
import shutil
import urllib2
import BaseHTTPServer
import re
import cookielib
import cgi
from urlparse import urlparse

URL=""


class DocumentData(object):
    def __init__(self):
        self.conversionTimestamp = datetime.datetime.now()
        self.shortDateString = self.conversionTimestamp.strftime("%Y-%m-%d")
        self.uuid = str(uuid.uuid1())
        self.title = "Untitled"
        self.author = "Unknown"
        self.url = ""
        self.language = "en"

        self.paragraphs = []
        self.documentBody = ""


    def parseDocument(self, sourceDocument):
        """
        sourceDocument (str) - input file contents
        """
        soup = bs4.BeautifulSoup(sourceDocument)
        
        title = soup.find("title")
        if title:
            self.title = title.string.strip()
        logging.info("TITLE: %s", self.title)

        if not self.url:
            url = soup.find("meta", {"property": "og:url"})
            if url and url.get("content"):
                self.url = url.get("content")
                try:
                    self.author= urlparse(url.get("content")).netloc.strip()
                except Exception:
                    pass
        logging.info("AUTHOR: %s", self.author)

        # extract what looks like text/headlines
        for paragraph in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
            if paragraph.getText():
                if "<script>" in unicode(paragraph):
                    continue
                content = paragraph.getText().strip()
                if content:
                    if re.match("h\\d", paragraph.name):
                        self.paragraphs.append(u"<%s>%s</%s>" % (paragraph.name, cgi.escape(content), paragraph.name))
                    else:
                        self.paragraphs.append(u"<p>%s</p>" % cgi.escape(content))

        self.documentBody = "\n".join(self.paragraphs)


CONTAINER_XML = (
ur"""<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
   </rootfiles>
</container>
""")

TOC_NCX_TEMPLATE = (
ur"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
   "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">

<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="en">
	<head>
		<meta name="dtb:uid" content="%(uuid)s"/>
	</head>
	<docTitle>
		<text>%(title)s</text>
	</docTitle>
	<docAuthor>
		<text>%(author)s</text>
	</docAuthor>

	<navMap>
		<navPoint class="section" id="navPoint-1" playOrder="1">
			<navLabel>
				<text>Content</text>
			</navLabel>
			<content src="text/content.xhtml"/>
		</navPoint>
	</navMap>
</ncx>
""")

CONTENT_OPF_TEMPLATE = (
ur"""<?xml version="1.0" encoding="UTF-8" ?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID" version="2.0" xml:lang="en">
	<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
		<dc:title>%(title)s</dc:title>
		<dc:rights> (c) %(author)s</dc:rights>
		<dc:creator opf:role="aut">%(author)s</dc:creator>
		<dc:type>Web page</dc:type>
		<dc:publisher>Converted by epuby</dc:publisher>
		<dc:source>%(url)s</dc:source>
		<dc:date opf:event="publication">%(shortDateString)s</dc:date>
		<dc:language>%(language)s</dc:language>
		<dc:identifier id="BookID" opf:scheme="CustomID">%(uuid)s</dc:identifier>

	</metadata>
	<manifest>
		<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
		<item id="content" href="text/content.xhtml" media-type="application/xhtml+xml"/>
	</manifest>
	<spine toc="ncx">
		<itemref idref="content" linear="yes"/>
	</spine>
	<guide>
		<reference type="text" title="Content" href="text/content.xhtml"/>
	</guide>
</package>
""")

CONTENT_TEMPLATE = (
ur"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
  <title>%(title)s</title>
</head>

<body>
	<h1>%(title)s</h1>
	<h2><a href="%(url)s">%(author)s</a></h2>
%(documentBody)s
</body>
</html>
""")

def initializePackageStructure(tmpDir):
    os.mkdir(os.path.join(tmpDir, "META-INF"))
    os.mkdir(os.path.join(tmpDir, "OEBPS"))
    os.mkdir(os.path.join(tmpDir, "OEBPS", "text"))
    with open(os.path.join(tmpDir, "mimetype"), "wb") as fileOut:
        fileOut.write("application/epub+zip")
    with open(os.path.join(tmpDir, "META-INF", "container.xml"), "wb") as fileOut:
        fileOut.write(CONTAINER_XML)


def generateTocNcx(tmpDir, documentData):
    with open(os.path.join(tmpDir, "OEBPS", "toc.ncx"), "wb") as tf:
        tf.write(TOC_NCX_TEMPLATE % documentData.__dict__)


def generateContentOpf(tmpDir, documentData):
    with open(os.path.join(tmpDir, "OEBPS", "content.opf"), "wb") as tf:
        tf.write(CONTENT_OPF_TEMPLATE % documentData.__dict__)


def generateContent(tmpDir, documentData):
    content = CONTENT_TEMPLATE % documentData.__dict__
    with open(os.path.join(tmpDir, "OEBPS", "text", "content.xhtml"), "wb") as tf:
        tf.write(content.encode("utf-8"))


def saveAsEPUB(tmpDir, outputDir, outputFilename):
    out = zipfile.ZipFile(os.path.join(outputDir, outputFilename), "w")
    for root, dirs, files in os.walk(tmpDir):
        for filename in files:
            out.write(os.path.join(root, filename), os.path.join(os.path.relpath(root, tmpDir), filename))
    out.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-f", help="input file", action="store")
    parser.add_argument("-u", help="URL to input file", action="store")
    parser.add_argument("-o", help="output directory", action="store")
    parser.add_argument("-d", help="debug mode", action="store_true", default=False)
    parser.add_argument("-v", help="verbose", action="store_true", default=False)
    args = parser.parse_args(sys.argv[1:])
    
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)
    
    logging.basicConfig(format="%(message)s", level=logging.DEBUG if args.d or args.v else logging.INFO)
    
    if args.f and args.u:
        logging.error("-f and -u options cannot be used together (ambiguous source)")
        sys.exit(1)
    
    if not args.f and not args.u:
        if URL:
            args.u = URL
            logging.warn("Using build in URL: %s", URL)
        else:
            logging.error("no input file provided")
            sys.exit(1)
    
    if not args.o:
        logging.warn("no output directory provided, files will be generated in current dir")
        args.o = "."
    if not os.path.exists(args.o):
        logging.error("provided output directory does not exist")
        sys.exit(1)
    if not os.path.isdir(args.o):
        logging.error("given output path is incorrect")
        sys.exit(1)
    
    documentData = DocumentData()
    
    try:
        if args.f:
            with open(args.f, "rb") as inputFile:
                sourceDocument = inputFile.read()
        else:
            if True:
                cj = cookielib.CookieJar()
                opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
                urllib2.install_opener(opener)
                response = urllib2.urlopen(args.u)
                sourceDocument = response.read()
    except urllib2.HTTPError as e:
        logging.error("Failed to open source URL (%d): %s", e.code, 
                          BaseHTTPServer.BaseHTTPRequestHandler.responses.get(e.code, "Unknown error"))
        sys.exit(1)
    except Exception, ex:
        logging.error("Error opening source document: %s", ex.message)
        sys.exit(1)
        
    tmpDir = ""
    if args.d:
        tmpDir = os.path.join(args.o, documentData.conversionTimestamp.strftime("%Y.%m.%d_%H.%M.%S"))
        os.mkdir(tmpDir)
    else:
        tmpDir = tempfile.mkdtemp()
    logging.debug("Using temp directory: %s", tmpDir)

    try:
        documentData.parseDocument(sourceDocument)
        initializePackageStructure(tmpDir)
        generateTocNcx(tmpDir, documentData)
        generateContentOpf(tmpDir, documentData)
        generateContent(tmpDir, documentData)
        outputFilename = "%s_%s.epub" % (documentData.title, documentData.shortDateString)
        outputFilename = string.translate(outputFilename.encode("utf-8"), None, "?*:\\/|")
        saveAsEPUB(tmpDir, args.o, outputFilename)
    finally:
        # keep temporary files in debug mode
        if not args.d and os.path.exists(tmpDir):
            logging.debug("Removing temp directory: %s", tmpDir)
            shutil.rmtree(tmpDir, True)


# The MIT License (MIT)
#
# Copyright (c) 2014 Maciej Borowik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
