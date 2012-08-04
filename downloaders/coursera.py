import argparse
import logging
import os
import re
import sys

try:
    from BeautifulSoup import BeautifulSoup
    from mechanize import Browser
except ImportError:
    print ("Not all the nessesary libs are installed. " +
           "Please see requirements.txt.")
    sys.exit(1)

EMAIL = ''
PASSWORD = ''
TARGETDIR = '/home/ktalwar/documents/coursera'
ILLEGAL_CHARS = ('<', '>', ':', '"', '|', '?', '*')
REG_URL_FILE = re.compile(r'.*/([^./]+)\.([\w\d]+)$', re.I)
REG_CONT_TYPE_EXT = re.compile(r'^.*/([\d\w]+)$', re.I)
REG_TXT_RES = re.compile(r'^(.*format)=txt$', re.I)
TYPES = ('pdf', 'ppt', 'txt', 'srt', 'movie')
TYPE_REPLACEMENT = {
    'txt': 'subtitles (text)', 'srt': 'subtitles (srt)',
    'movie': 'video (mp4)'
}
DEFAULT_EXT = {
    'pdf': 'pdf', 'ppt': 'ppt', 'subtitles (text)': 'txt',
    'subtitles (srt)': 'srt', 'video (mp4)': 'mp4'
}




tag_re = re.compile('^[a-z0-9]+$')

attribselect_re = re.compile(
    r'^(?P<tag>\w+)?\[(?P<attribute>\w+)(?P<operator>[=~\|\^\$\*]?)' + 
    r'=?"?(?P<value>[^\]"]*)"?\]$'
)

# /^(\w+)\[(\w+)([=~\|\^\$\*]?)=?"?([^\]"]*)"?\]$/
#   \---/  \---/\-------------/    \-------/
#     |      |         |               |
#     |      |         |           The value
#     |      |    ~,|,^,$,* or =
#     |   Attribute 
#    Tag

def attribute_checker(operator, attribute, value=''):
    """
    Takes an operator, attribute and optional value; returns a function that
    will return True for elements that match that combination.
    """
    return {
        '=': lambda el: el.get(attribute) == value,
        # attribute includes value as one of a set of space separated tokens
        '~': lambda el: value in el.get(attribute, '').split(),
        # attribute starts with value
        '^': lambda el: el.get(attribute, '').startswith(value),
        # attribute ends with value
        '$': lambda el: el.get(attribute, '').endswith(value),
        # attribute contains value
        '*': lambda el: value in el.get(attribute, ''),
        # attribute is either exactly value or starts with value-
        '|': lambda el: el.get(attribute, '') == value \
            or el.get(attribute, '').startswith('%s-' % value),
    }.get(operator, lambda el: el.has_key(attribute))


def select(soup, selector):
    """
    soup should be a BeautifulSoup instance; selector is a CSS selector 
    specifying the elements you want to retrieve.
    """
    tokens = selector.split()
    current_context = [soup]
    for token in tokens:
        m = attribselect_re.match(token)
        if m:
            # Attribute selector
            tag, attribute, operator, value = m.groups()
            if not tag:
                tag = True
            checker = attribute_checker(operator, attribute, value)
            found = []
            for context in current_context:
                found.extend([el for el in context.findAll(tag) if checker(el)])
            current_context = found
            continue
        if '#' in token:
            # ID selector
            tag, id = token.split('#', 1)
            if not tag:
                tag = True
            el = current_context[0].find(tag, {'id': id})
            if not el:
                return [] # No match
            current_context = [el]
            continue
        if '.' in token:
            # Class selector
            tag, klass = token.split('.', 1)
            if not tag:
                tag = True
            found = []
            for context in current_context:
                found.extend(
                    context.findAll(tag,
                        {'class': lambda attr: attr and klass in attr.split()}
                    )
                )
            current_context = found
            continue
        if token == '*':
            # Star selector
            found = []
            for context in current_context:
                found.extend(context.findAll(True))
            current_context = found
            continue
        # Here we should just have a regular tag
        if not tag_re.match(token):
            return []
        found = []
        for context in current_context:
            found.extend(context.findAll(token))
        current_context = found
    return current_context

def monkeypatch(BeautifulSoupClass=None):
    """
    If you don't explicitly state the class to patch, defaults to the most 
    common import location for BeautifulSoup.
    """
    if not BeautifulSoupClass:
        from BeautifulSoup import BeautifulSoup as BeautifulSoupClass
    BeautifulSoupClass.findSelect = select

def unmonkeypatch(BeautifulSoupClass=None):
    if not BeautifulSoupClass:
        from BeautifulSoup import BeautifulSoup as BeautifulSoupClass
    delattr(BeautifulSoupClass, 'findSelect')







class CourseraDownloader(object):
    login_url = ''
    home_url = ''
    lectures_url = ''
    course_name = ''

    def __init__(self, config):
        self.parts_ids = config['parts']
        self.rows_ids = config['rows']
        self.types = config['types']
        self.force = config['force']
        self.escape = config['escape']
        self.br = Browser()
        self.br.set_handle_robots(False)

    def authenticate(self):
        self.br.open(self.login_url)
        self.br.form = self.br.forms().next()
        self.br['email'] = EMAIL
        self.br['password'] = PASSWORD
        self.br.submit()
        home_page = self.br.open(self.home_url)
        if not self.is_authenticated(home_page.read()):
            logging.critical("couldn't authenticate")
            sys.exit(1)
        logging.info("successfully authenticated")

    def is_authenticated(self, test_page):
        m = re.search(
            'https://class.coursera.org/%s/auth/logout' % self.course_name,
            test_page)
        return m is not None

    def download(self):
        course_dir = os.path.join(TARGETDIR, self.course_name)
        if not os.path.exists(course_dir):
            os.mkdir(course_dir)
        page = self.br.open(self.lectures_url)
        doc = BeautifulSoup(page)
        parts, part_titles = self.get_parts(doc)
        for idx, part in enumerate(parts):
            if self.item_is_needed(self.parts_ids, idx):
                part_dir = os.path.join(
                    course_dir,
                    '%02d - %s' % ((idx + 1),
                    self.escape_name(part_titles[idx].text.strip())))
                self.download_part(part_dir, part)

    def download_part(self, dir_name, part):
        if not os.path.exists(dir_name):
            os.mkdir(dir_name)
        rows, row_names = self.get_rows(part)
        for idx, row in enumerate(rows):
            if self.item_is_needed(self.rows_ids, idx):
                self.download_row(dir_name, '%02d - %s' % ((idx + 1),
                                  row_names[idx].text.strip()), row)

    def download_row(self, dir_name, name, row):
        resources = self.get_resources(row)
        for resource in resources:
            if self.item_is_needed(self.types, resource[1]):
                self.download_resource(dir_name, name, resource)

    def download_resource(self, dir_name, name, resource):
        res_url = resource[0]
        res_type = resource[1]
        url, content_type = self.get_real_resource_info(res_url)
        ext = self.get_file_ext(url, content_type, res_type)
        filename = self.get_file_name(dir_name, name, ext)
        self.retrieve(url, filename)

    def retrieve(self, url, filename):
        if os.path.exists(filename) and not self.force:
            logging.info("skipping file '%s'" % filename)
        else:
            logging.info("downloading file '%s'" % filename)
            logging.debug("URL: %s" % url)
            try:
                self.br.retrieve(url, filename, reporter)
            except KeyboardInterrupt:
                if os.path.exists(filename): os.remove(filename)
                raise
            except Exception, ex:
                if os.path.exists(filename): os.remove(filename)
                logging.debug(ex)
                logging.info("couldn't download the file")

    def item_is_needed(self, etalons, sample):
        return (len(etalons) == 0) or (sample in etalons)

    def get_file_name(self, dir_name, name, ext):
        name = self.escape_name(name)
        return ('%s.%s' % (os.path.join(dir_name, name), ext))

    def escape_name(self, name):
        name = name.replace('/', '_').replace('\\', '_')
        if self.escape:
            for c in ILLEGAL_CHARS:
                name = name.replace(c, '_')
        return name

    def get_real_resource_info(self, res_url):
        try:
            src = self.br.open(res_url)
            try:
                url = src.geturl()
                content_type = src.info().get('content-type', '')
                return (url, content_type)
            finally:
                src.close()
        except:
            return (res_url, '')

    def get_file_ext(self, url, content_type, res_type):
        m = REG_URL_FILE.search(url)
        if m:
            return m.group(2)
        m = REG_CONT_TYPE_EXT.match(content_type)
        if m:
            return m.group(1)
        return DEFAULT_EXT[res_type]

    def get_parts(self, doc):
        items = select(doc, 'ul.item_section_list')
        titles = select(doc, 'h3.list_header')
        return items, titles

    def get_rows(self, doc):
        rows = select(doc, 'div.item_resource')
        titles = select(doc, 'a.lecture-link')
        return rows, titles

    def get_resources(self, doc):
        resources = []
        for a in select(doc, 'a'):
            url = a.get('href')
            title = a.get('title').lower()
            resources.append((url, title))
        return resources


class GenericDownloader(object):
    @classmethod
    def downloader(cls, course):
        dl_name = course.capitalize() + 'Downloader'
        dl_bases = (CourseraDownloader,)
        dl_dict = dict(
            login_url=('https://www.coursera.org/%s/auth/auth_redirector' +
                       '?type=login&subtype=normal&email=') % course,
            home_url='https://class.coursera.org/%s/class/index' % course,
            lectures_url='https://class.coursera.org/%s/lecture/index' %
                         course,
            course_name=course)
        cls = type(dl_name, dl_bases, dl_dict)
        return cls


class DecrementAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        values = [value - 1 for value in values]
        setattr(namespace, self.dest, values)


class TypeReplacementAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        values = [TYPE_REPLACEMENT[value] if value in TYPE_REPLACEMENT.keys()
                  else value for value in values]
        setattr(namespace, self.dest, values)


def reporter(blocknum, bs, size):
    if is_verbose() and size > 0:
        block_count = size / bs + 1 if size % bs != 0 else size / bs
        fraction = float(blocknum) / block_count
        width = 50
        stars = '*' * int(width * fraction)
        spaces = ' ' * (width - len(stars))
        info = '[ %s%s ] [%s %%]' % (stars, spaces, int(fraction * 100))
        sys.stdout.write(info)
        if blocknum < block_count:
            sys.stdout.write('\r')
        else:
            sys.stdout.write('\n')


def create_arg_parser():
    parser = argparse.ArgumentParser(
        description="Downloads materials from Coursera.")
    parser.add_argument('course')
    parser.add_argument('-p', '--parts', action=DecrementAction,
                        nargs='*', default=[], type=int)
    parser.add_argument('-r', '--rows', action=DecrementAction,
                        nargs='*', default=[], type=int)
    parser.add_argument('-t', '--types', action=TypeReplacementAction,
                        nargs='*', default=[], choices=TYPES)
    parser.add_argument('-f', '--force', action='store_true')
    parser.add_argument('-e', '--escape', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument(
        '-l', '--logging', default='critical',
        choices=('debug', 'info', 'warning', 'error', 'critical'))
    return parser


def create_config(ns):
    config = dict()
    config['parts'] = ns.parts
    config['rows'] = ns.rows
    config['types'] = ns.types
    config['force'] = ns.force
    config['escape'] = ns.escape
    return config


def get_downloader_class(course):
    return GenericDownloader.downloader(course)


def is_verbose():
    return logging.getLogger().level <= logging.INFO


def configure_logging(ns):
    if ns.verbose:
        level = logging.INFO
    else:
        if ns.logging == 'debug':
            level = logging.DEBUG
        elif ns.logging == 'info':
            level = logging.INFO
        elif ns.logging == 'warning':
            level = logging.WARNING
        elif ns.logging == 'error':
            level = logging.ERROR
        elif ns.logging == 'critical':
            level = logging.CRITICAL
    logging.basicConfig(level=level, format="%(message)s")


def main():
    arg_parser = create_arg_parser()
    ns = arg_parser.parse_args(sys.argv[1:])
    configure_logging(ns)
    config = create_config(ns)
    dl_class = get_downloader_class(ns.course)
    dl = dl_class(config)
    dl.authenticate()
    dl.download()


if __name__ == '__main__':
    main()
