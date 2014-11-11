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
from xml.sax.saxutils import quoteattr

URL=""

INCLUDE_IMAGES = False  # global override (for testing)

FONT_SCHEMES = {
    "global_TNR" : 
ur"""
@font-face {
font-family: "Times New Roman";
font-weight: normal;
font-style: normal;
src: url(res:///ebook/fonts/../../mnt/sdcard/fonts/times.ttf);
}

@font-face {
font-family: "Times New Roman";
font-weight: bold;
font-style: normal;
src: url(res:///ebook/fonts/../../mnt/sdcard/fonts/timesbd.ttf);
}

@font-face {
font-family: "Times New Roman";
font-weight: normal;
font-style: italic;
src:url(res:///ebook/fonts/../../mnt/sdcard/fonts/timesi.ttf);
}

@font-face {
font-family: "Times New Roman";
font-weight: bold;
font-style: italic;
src: url(res:///ebook/fonts/../../mnt/sdcard/fonts/timesbi.ttf);
}

body, div, p {
font-family: "Times New Roman";
}
"""
}

#~ EXTRA_CSS = [
    #~ FONT_SCHEMES["global_TNR"]
#~ ]

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
        self.templateValues = {}
        self.images = []


    def getAllowedParagraphTagNames(self, includeDIV=False, includeIMG=INCLUDE_IMAGES):
        tags = ["p", "li", "pre", "h1", "h2", "h3", "h4", "h5", "h6"]  #, "font"
        if includeDIV:
            tags.append("div")
        if includeIMG:
            tags.append("img")
        return tags


    def parseDocument(self, sourceDocument, includeDIV=False, includeIMG=INCLUDE_IMAGES):
        """
        sourceDocument (str) - input file contents
        """
        soup = bs4.BeautifulSoup(sourceDocument)
        
        title = soup.find("title")
        if title:
            try:
                self.title = title.string.decode("utf-8").strip()
            except UnicodeEncodeError, ex:
                logging.warn(ex)
                self.title = filter(lambda x: x in string.printable, title.string).strip()
        self.title = re.sub("\n", " ", self.title)
        logging.info("TITLE: %s", self.title)

        if not self.url:
            url = soup.find("meta", {"property": "og:url"})
            if url and url.get("content"):
                self.url = url.get("content").decode("utf-8")
                try:
                    self.author= urlparse(self.url).netloc.strip()
                except Exception:
                    pass
        logging.info("AUTHOR: %s", self.author)

        # strip all comments
        for comment in soup.findAll(text=lambda tag: isinstance(tag, bs4.Comment)):
            comment.extract()

        # strip all scripts
        for scriptTag in soup.findAll("script"):
            scriptTag .extract()

        # text passages containing <br> tags into multiple paragraphs
        brSplitRegexp = re.compile(r"\<\s*br\s*/{0,1}\>", re.I)

        # some blogs define section id="content", let's try to be smart about it
        contentSelectors = [
            {"name": "article"},
            {"name": "section", "class": "main_cont"},
            {"name": "div", "id": "content"},
            {"name": "div", "class": "content"},
            {"name": "div", "class": "contentbox"},
            {"name": "section", "id": "content"},
            {"name": "div", "id": "maincontent"},
            {"name": "div", "id": "main-content"},
            {"name": "div", "class": "single-archive"},
            {"name": "div", "class": "blogcontent"},
            {"name": "div", "class": "post"},
        ]
        contentCandidates = []
        for selector in contentSelectors:
            contentSection = soup.find(**selector)
            if contentSection:
                contentCandidates.append(contentSection)
        
        # select the largest section from the ones filtered out above
        if contentCandidates:
            soup = ""
            for contentCandidate in contentCandidates:
                if len(str(contentCandidate)) > len(str(soup)):
                    soup = contentCandidate
            logging.info("Stripping everything except for the following section: %s %s", soup.name, repr(soup.attrs))

        imageCache = {}
        def processImage(tag, imgCounter=[0]):
            if "src" in imgTag.attrs:
                imgUrl = imgTag["src"]
                if imgUrl in imageCache:
                    localName = imageCache[imgUrl]
                else:
                    localName = "%s%s" % (str(imgCounter[0]), os.path.splitext(imgUrl.split("?")[0])[1])
                    self.images.append([localName, imgTag["src"]])
                    imageCache[imgUrl] = localName
                self.paragraphs.append("<img src=%s/>" % quoteattr("../img/%s" % localName))
                imgCounter[0] += 1

        # extract what looks like text/headlines
        for paragraph in soup.find_all(self.getAllowedParagraphTagNames(includeDIV, includeIMG)):
            if paragraph.getText():
                for content in brSplitRegexp.split(unicode(paragraph)):
                    content = bs4.BeautifulSoup(content).getText().strip()
                    if content:
                        if re.match("h\\d", paragraph.name):
                            self.paragraphs.append(u"<%s>%s</%s>" % (paragraph.name, cgi.escape(content), paragraph.name))
                        if paragraph.name in ("pre", "li"):
                            self.paragraphs.append(u"<%s>%s</%s>" % (paragraph.name, cgi.escape(content), paragraph.name))
                        elif paragraph.name == "img":
                            processImage(paragraph)
                        else:
                            self.paragraphs.append(u"<p>%s</p>" % cgi.escape(content))
            if includeIMG:
                # handle images within paragraph
                for imgTag in paragraph.find_all("img"):
                    processImage(imgTag)

        self.documentBody = "\n".join(self.paragraphs)
        
        self.templateValues = {
            "title": cgi.escape(self.title),
            "url": cgi.escape(self.url),
            "urlAttribute": quoteattr(self.url),
            "author": cgi.escape(self.author),
            "shortDateString": self.shortDateString,
            "uuid": self.uuid,
            "language": self.language,
            "documentBody": self.documentBody
        }


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
  <link rel="stylesheet" type="text/css" href="content.css"/>
</head>

<body>
	<h1>%(title)s</h1>
	<h2><a href=%(urlAttribute)s>%(author)s</a></h2>
%(documentBody)s
</body>
</html>
""")

def initializePackageStructure(tmpDir):
    os.mkdir(os.path.join(tmpDir, "META-INF"))
    os.mkdir(os.path.join(tmpDir, "OEBPS"))
    os.mkdir(os.path.join(tmpDir, "OEBPS", "text"))
    os.mkdir(os.path.join(tmpDir, "OEBPS", "img"))
    with open(os.path.join(tmpDir, "mimetype"), "wb") as fileOut:
        fileOut.write("application/epub+zip")
    with open(os.path.join(tmpDir, "META-INF", "container.xml"), "wb") as fileOut:
        fileOut.write(CONTAINER_XML)


def generateTocNcx(tmpDir, documentData):
    with open(os.path.join(tmpDir, "OEBPS", "toc.ncx"), "wb") as tf:
        tf.write(TOC_NCX_TEMPLATE % documentData.templateValues)


def generateContentOpf(tmpDir, documentData):
    with open(os.path.join(tmpDir, "OEBPS", "content.opf"), "wb") as tf:
        tf.write(CONTENT_OPF_TEMPLATE % documentData.templateValues)


def generateContent(tmpDir, documentData):
    content = CONTENT_TEMPLATE % documentData.templateValues
    with open(os.path.join(tmpDir, "OEBPS", "text", "content.xhtml"), "wb") as tf:
        tf.write(content.encode("utf-8"))


def generateCSS(tmpDir, documentData):
    content = "\n".join(EXTRA_CSS)
    with open(os.path.join(tmpDir, "OEBPS", "text", "content.css"), "wb") as tf:
        tf.write(content.encode("utf-8"))


def downloadImages(tmpDir, documentData):
    for (localName, url) in documentData.images:
        try:
            imgRequest = urllib2.Request(url)
            with open(os.path.join(tmpDir, "OEBPS", "img", localName), "wb") as imgFile:
                imgFile.write(urllib2.urlopen(imgRequest).read())
                logging.info("Downloaded image: %s", url)
        except ValueError:
            logging.warn("Skipping image: %s", url)

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
    parser.add_argument("--div",
                        help="include <div> tags (to use when a page uses <div> instead of <p> for paragraphs)",
                        action="store_true")
    parser.add_argument("--img", help="include images", action="store_true", default=False)
    parser.add_argument("-d", help="debug mode", action="store_true", default=False)
    parser.add_argument("-v", help="verbose", action="store_true", default=False)
    args = parser.parse_args(sys.argv[1:])
    
    if not URL and len(sys.argv) < 2:
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
        documentData.parseDocument(sourceDocument, args.div, INCLUDE_IMAGES or args.img)
        initializePackageStructure(tmpDir)
        generateTocNcx(tmpDir, documentData)
        generateContentOpf(tmpDir, documentData)
        generateContent(tmpDir, documentData)
        generateCSS(tmpDir, documentData)
        downloadImages(tmpDir, documentData)
        outputFilename = "%s_%s.epub" % (documentData.title.replace('"', ""), documentData.shortDateString)
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
