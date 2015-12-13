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

INCLUDE_DIV = True  # global override (for testing)
INCLUDE_IMAGES = False  # global override (for testing)
INCLUDE_TABLES = False
ENABLE_STRIPPING = True  # strip only selected sections (e.g. article, etc.) - try to narrow down to only interesting content

# NOTE: special font schemes for Sony PRS-T1 reader - .ttf files should be copied to READER:/fonts/
FONT_SCHEMES = {
    "TNR" : 
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
""",
    "JP":  # rendering japanese characters using Aozora Mincho font http://www.freejapanesefont.com/aozora-mincho-download/
ur"""
@font-face {
font-family: "Mincho";
font-weight: normal;
src: url(res:///ebook/fonts/../../mnt/sdcard/fonts/AozoraMinchoRegular.ttf);
}
@font-face {
font-family: "Mincho";
font-weight: bold;
src: url(res:///ebook/fonts/../../mnt/sdcard/fonts/AozoraMincho-bold.ttf);
}

body, div, p {
font-family: "Mincho";
}
""",
    "CHN":  # rendering chinese with http://www.babelstone.co.uk/Fonts/Han.html
ur"""
@font-face {
font-family: "BabelStoneHan";
font-weight: normal;
src: url(res:///ebook/fonts/../../mnt/sdcard/fonts/BabelStoneHan.ttf);
}
@font-face {
font-family: "BabelStoneHan";
font-weight: bold;
src: url(res:///ebook/fonts/../../mnt/sdcard/fonts/BabelStoneHan-bold.ttf);
}

body, div, p {
font-family: "BabelStoneHan";
}
"""
}

EXTRA_CSS = [
    #~ FONT_SCHEMES["JP"],
    #~ FONT_SCHEMES["TNR"]
    #~ FONT_SCHEMES["CHN"]
]

MAX_LINE_LEN = 46  # for splitting long lines in <pre> targs

class DocumentData(object):
    def __init__(self, url=None):
        self.conversionTimestamp = datetime.datetime.now()
        self.shortDateString = self.conversionTimestamp.strftime("%Y-%m-%d")
        self.uuid = str(uuid.uuid1())
        self.title = "Untitled"
        self.author = "Unknown"
        self.url = url or ""
        self.language = "en"

        self.paragraphs = []
        self.documentBody = ""
        self.templateValues = {}
        self.images = []


    def getAllowedParagraphTagNames(self, includeDIV=False, includeIMG=False, includeTables=False):
        tags = ["p", "strong", "em", "li", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"]  #, "font", "center"
        if includeDIV:
            tags.append("div")
        if includeIMG:
            tags.append("img")
            tags.append("figure")
        if includeTables:
            tags.append("table")
        return tags


    def parseDocument(self, sourceDocument, includeDIV=False, includeIMG=False, includeTables=False):
        """
        sourceDocument (str) - input file contents
        """
        soup = bs4.BeautifulSoup(sourceDocument)
        
        title = soup.find("title")
        if title and title.string:
            try:
                self.title = title.string.decode("utf-8").strip()
            except UnicodeEncodeError, ex:
                logging.warn(ex)
                self.title = filter(lambda x: x in string.printable, title.string).strip()
        else:
            self.title = self.url or "Untitled"
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
            {"name": "article", "role": "main"},
            {"name": "section", "class": "main_cont"},
            {"name": "div", "id": "sn-content"},
            {"name": "div", "id": "content"},
            {"name": "div", "data-zone": "contentSection"},
            #{"name": "div", "class": "content"},
            {"name": "div", "class": "contentbox"},
            {"name": "section", "id": "content"},
            {"name": "div", "id": "maincontent"},
            {"name": "div", "id": "main-content"},
            {"name": "div", "class": "main-content"},
            {"name": "div", "class": "single-archive"},
            {"name": "div", "class": "blogcontent"},
            {"name": "div", "class": "post"},
            {"name": "div", "class": "hentry"},
            {"name": "div", "class": "article-single-container"},
            {"name": "div", "id": "story-content"},
            #~ {"name": "div", "class": "col-left-story"},
        ]
        contentCandidates = []
        if ENABLE_STRIPPING:
            for selector in contentSelectors:
                contentSections = soup.find_all(**selector)
                if contentSections:
                    contentCandidates.extend(contentSections)
        
        # select the largest section from the ones filtered out above
        if contentCandidates:
            soup = ""
            for contentCandidate in contentCandidates:
                if len(str(contentCandidate)) > len(str(soup)):
                    soup = contentCandidate
            logging.info("Stripping everything except for the following section: %s %s", soup.name, repr(soup.attrs))

        excludedContentSelectors = [
            {"name": "div", "class": "more-from"},
            {"name": "div", "class": "more-in-this-section"},
            {"name": "div", "class": "breaking-stories"},
            {"name": "ul", "data-vr-zone": "most-read-stories"},
            {"name": "div", "id": "topstories"},
            {"name": "div", "id": "mostshared"},
            {"name": "div", "class": "blog-archive-list"},
            {"name": "div", "id": "stb-header"},
            {"name": "ul", "class": "navigation-list"},
            {"name": "ul", "class": "tag-list"},
            {"name": "ul", "class": "mainNav"},
            {"name": "div", "class": "secLinks"},
            {"name": "div", "id": "tmg-related-links"},
            {"name": "div", "class": "related_links"},
            {"name": "div", "class": "section-puffs"},
            {"name": "div", "class": "artCommercial"},
            {"name": "div", "class": "mostPopular"},
            {"name": "div", "class": "PageList"},
            {"name": "div", "class": "BlogArchive"},
            {"name": "ul", "class": "menu1"},
            {"name": "ul", "class": "menu2"},
            {"name": "div", "bucket-id": "top_stories_05"},
            {"name": "div", "class": "printHide"},
            {"name": "aside", "class": "related-coverage-marginalia"},
            {"name": "aside", "class": "collection-theme-latest-headlines"},
            {"name": "div", "class": "m-site-nav"},
            {"name": "div", "id": "top-line-navigation"},
            {"name": "div", "id": "primary-navigation"},
            {"name": "nav"},
            {"name": "div", "class": "topics_holder"},
        ]
        if ENABLE_STRIPPING:
            for selector in excludedContentSelectors:
                contentSections = soup.find_all(**selector)
                if contentSections:
                    print "Removing section:", selector
                    for section in contentSections:
                        section.extract()

        imageCache = {}
        def processImage(imgTag, imgCounter=[0]):
            imgUrl = None
            if "src" in imgTag.attrs:
                imgUrl = imgTag["src"]
                srcAttrName = 'src'
            elif 'data-src' in imgTag.attrs:
                imgUrl = imgTag['data-src']
                srcAttrName = 'data-src'
            if imgUrl:
                if imgUrl in imageCache:
                    localName = imageCache[imgUrl]
                else:
                    localName = "%s%s" % (str(imgCounter[0]), os.path.splitext(imgUrl.split("?")[0])[1])
                    imageUrl = imgTag[srcAttrName]
                    if imageUrl.startswith("/"):
                        try:
                            parsedUrl = urlparse(self.url)
                            hostUrl = "%s://%s" % (parsedUrl.scheme, parsedUrl.netloc)
                        except Exception:
                            pass
                        if imageUrl.startswith("//"):
                            hostProtocol = hostUrl.split('/')[0]
                            imageUrl = "%s%s" % (hostProtocol, imageUrl)
                        else:
                            imageUrl = "%s%s" % (hostUrl, imageUrl)
                    self.images.append([localName, imageUrl])
                    imageCache[imgUrl] = localName
                self.paragraphs.append("<img src=%s/>" % quoteattr("../img/%s" % localName))
                imgCounter[0] += 1

        # extract what looks like text/headlines
        allowedTags = self.getAllowedParagraphTagNames(includeDIV, includeIMG, includeTables)
        for paragraph in soup.find_all(allowedTags):
            # try to skip nested DIVs
            if paragraph.name == 'div':
                # look only at DIVs containing text directly, so they don't get picked up multiple times if the div contains another divs...
                nonEmptyChildren = []
                for child in paragraph.children:
                    if isinstance(child, bs4.element.NavigableString):
                        if child.strip():
                            nonEmptyChildren.append(child)
                #~ if "Just to clarify, if somebody saw one of your passwords, would they be able to work out the rest of them?" in paragraph.getText():
                    #~ import ipdb; ipdb.set_trace()

                if not nonEmptyChildren:
                    continue

            if paragraph.parent.name != 'div' and paragraph.parent.name in allowedTags and paragraph.parent.name != 'div':
                # make sure not included twice, e.g. <strong> inside <p>
                continue

            if paragraph.getText():
                for content in brSplitRegexp.split(unicode(paragraph)):
                    content = bs4.BeautifulSoup(content).getText().strip()
                    if content:
                        newContent = None
                        if re.match("h\\d", paragraph.name):
                            newContent = u"<%s>%s</%s>" % (paragraph.name, cgi.escape(content), paragraph.name)
                        if paragraph.name in ("pre", "li", "blockquote"):
                            paragraphname = paragraph.name
                            if paragraph.name == 'blockquote' and '\n' in content.strip():
                                paragraphname = 'pre'  # use formatting as for source code
                            if paragraphname == 'pre':
                                # wrap long lines (that my Sony PRS-T1 cannot wrap inside <pre> tags)
                                import textwrap
                                content = '\n'.join(textwrap.wrap(content, MAX_LINE_LEN))
                            newContent = u"<%s>%s</%s>" % (paragraphname, cgi.escape(content), paragraphname)
                        elif paragraph.name == "img":
                            processImage(paragraph)
                        elif paragraph.name == "table":
                            newContent = unicode(paragraph)
                        else:
                            newContent = u"<p>%s</p>" % cgi.escape(content)
                        if newContent and (not self.paragraphs or newContent != self.paragraphs[-1]):  # ignore duplicates
                            self.paragraphs.append(newContent)
            elif includeIMG and paragraph.name == "img":
                processImage(paragraph)
            if includeIMG:
                # handle images within paragraph
                for imgTag in paragraph.find_all("img"):
                    processImage(imgTag)
                if paragraph.name == 'figure':
                    for imgTag in paragraph.find_all('div'):
                        if 'data-src' in imgTag.attrs:
                            processImage(imgTag)

        self.documentBody = u"\n".join(self.paragraphs)
        
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


def generateCSS(tmpDir, documentData, extraCSS=None):
    if extraCSS is None:
        extraCSS = []
    content = "\n".join(extraCSS)
    with open(os.path.join(tmpDir, "OEBPS", "text", "content.css"), "wb") as tf:
        tf.write(content.encode("utf-8"))


def downloadImages(tmpDir, documentData):
    for (localName, url) in documentData.images:
        try:
            logging.info("Downloading image: %s", url)
            imgRequest = urllib2.Request(url)
            try:
                imgData = urllib2.urlopen(imgRequest).read()
                with open(os.path.join(tmpDir, "OEBPS", "img", localName), "wb") as imgFile:
                    imgFile.write(imgData)
            except urllib2.HTTPError, ex:
                logging.error("Failed to download image: %s", ex.message)
        except ValueError:
            logging.warn("Skipping image: %s", url)

def saveAsEPUB(tmpDir, outputDir, outputFilename):
    out = zipfile.ZipFile(os.path.join(outputDir, outputFilename), "w")
    for root, dirs, files in os.walk(tmpDir):
        for filename in files:
            out.write(os.path.join(root, filename), os.path.join(os.path.relpath(root, tmpDir), filename))
    out.close()



def downloadWebPageSource(url):
    """
    Download HTML given an URL to web page.
    """
    try:
        cj = cookielib.CookieJar()
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
        urllib2.install_opener(opener)
        response = urllib2.urlopen(url)
        #~ print response.info()
        contentEncoding = response.info().getheader('Content-Encoding')
        if contentEncoding == 'gzip':
            logging.warn('Content-Encoding is gzip - inflating')
            import zlib
            return zlib.decompress(response.read(), 16 + zlib.MAX_WBITS)
        return response.read()
    except urllib2.HTTPError as e:
        logging.error("Failed to open source URL (%d): %s", e.code, 
                          BaseHTTPServer.BaseHTTPRequestHandler.responses.get(e.code, "Unknown error"))
        raise


def generateEPUB(url, sourceDocument, outDir, includeDIV=False, includeIMG=False, includeTables=False, extraCSS=None, debug=False):
    """
    Generate .epub file.
    ARGS:
        url (str)
        sourceDocument (str) - HTML of the page being saved to .epub
        outDir (str) - output directory
        includeDIV (bool)
        includeIMG (bool)
        includeTables (bool)
        extraCSS (list[str]) - additional CSS to include in .epub, e.g. custom fonts
    RETURNS:
        str - path to output file
    """
    documentData = DocumentData(url)

    tmpDir = ""
    if debug:
        tmpDir = os.path.join(outDir, documentData.conversionTimestamp.strftime("%Y.%m.%d_%H.%M.%S"))
        os.mkdir(tmpDir)
    else:
        tmpDir = tempfile.mkdtemp()
    logging.debug("Using temp directory: %s", tmpDir)

    try:
        documentData.parseDocument(sourceDocument, includeDIV=includeDIV, includeIMG=includeIMG, includeTables=includeTables)
        initializePackageStructure(tmpDir)
        generateTocNcx(tmpDir, documentData)
        generateContentOpf(tmpDir, documentData)
        generateContent(tmpDir, documentData)
        generateCSS(tmpDir, documentData, extraCSS)
        downloadImages(tmpDir, documentData)
        allowedChars = ['_', '-', '!', ' ']
        sanitizedTitle = filter(lambda ch: ch.isalpha() or ch.isdigit() or ch in allowedChars, documentData.title)
        outputFilename = "%s_%s.epub" % (sanitizedTitle, documentData.shortDateString)
        outputFilename = string.translate(outputFilename.encode("utf-8"), None, "?*:\\/|")
        saveAsEPUB(tmpDir, outDir, outputFilename)
        return os.path.join(outDir, outputFilename)
    finally:
        # keep temporary files in debug mode
        if not debug and os.path.exists(tmpDir):
            logging.debug("Removing temp directory: %s", tmpDir)
            shutil.rmtree(tmpDir, True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-f", help="input file", action="store")
    parser.add_argument("-u", help="URL to input file", action="store")
    parser.add_argument("-o", help="output directory", action="store")
    parser.add_argument("--div",
                        help="include <div> tags (to use when a page uses <div> instead of <p> for paragraphs)",
                        action="store_true")
    parser.add_argument("--img", help="include images", action="store_true", default=False)
    parser.add_argument("-t", help="include tables (use with caution)", action="store_true", default=False)
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
    
    try:
        if args.f:
            with open(args.f, "rb") as inputFile:
                sourceDocument = inputFile.read()
        else:
            sourceDocument = downloadWebPageSource(args.u)
    except urllib2.HTTPError as e:
        logging.error("Failed to open source URL (%d): %s", e.code, 
                          BaseHTTPServer.BaseHTTPRequestHandler.responses.get(e.code, "Unknown error"))
        sys.exit(1)
    except Exception, ex:
        logging.error("Error opening source document: %s", ex.message)
        sys.exit(1)
        
    generateEPUB(args.u,  # url
                 sourceDocument,
                 args.o,  # outDir
                 includeDIV=INCLUDE_DIV or args.div,
                 includeIMG=INCLUDE_IMAGES or args.img,
                 includeTables=INCLUDE_TABLES or args.t,
                 extraCSS=EXTRA_CSS,
                 debug=args.d)


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
