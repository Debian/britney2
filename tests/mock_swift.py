# Mock a Swift server with autopkgtest results
# Author: Martin Pitt <martin.pitt@ubuntu.com>

import os
import tarfile
import io
import sys
import socket
import time
import tempfile
import json

try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
except ImportError:
    # Python 2
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from urlparse import urlparse, parse_qs


class SwiftHTTPRequestHandler(BaseHTTPRequestHandler):
    '''Mock swift container with autopkgtest results

    This accepts retrieving a particular result.tar (e. g.
    /container/path/result.tar) or listing the container contents
    (/container/?prefix=foo&delimiter=@&marker=foo/bar).
    '''
    # map container -> result.tar path -> (exitcode, testpkg-version[, testinfo])
    results = {}

    def do_GET(self):
        p = urlparse(self.path)
        path_comp = p.path.split('/')
        container = path_comp[1]
        path = '/'.join(path_comp[2:])
        if path:
            self.serve_file(container, path)
        else:
            self.list_container(container, parse_qs(p.query))

    def serve_file(self, container, path):
        if os.path.basename(path) != 'result.tar':
            self.send_error(404, 'File not found (only result.tar supported)')
            return
        try:
            fields = self.results[container][os.path.dirname(path)]
            try:
                (exitcode, pkgver, testinfo) = fields
            except ValueError:
                (exitcode, pkgver) = fields
                testinfo = None
        except KeyError:
            self.send_error(404, 'File not found')
            return

        self.send_response(200)
        self.send_header('Content-type', 'application/octet-stream')
        self.end_headers()

        tar = io.BytesIO()
        with tarfile.open('result.tar', 'w', tar) as results:
            # add exitcode
            contents = ('%i' % exitcode).encode()
            ti = tarfile.TarInfo('exitcode')
            ti.size = len(contents)
            results.addfile(ti, io.BytesIO(contents))
            # add testpkg-version
            if pkgver is not None:
                contents = pkgver.encode()
                ti = tarfile.TarInfo('testpkg-version')
                ti.size = len(contents)
                results.addfile(ti, io.BytesIO(contents))
            # add testinfo.json
            if testinfo:
                contents = json.dumps(testinfo).encode()
                ti = tarfile.TarInfo('testinfo.json')
                ti.size = len(contents)
                results.addfile(ti, io.BytesIO(contents))

        self.wfile.write(tar.getvalue())

    def list_container(self, container, query):
        try:
            objs = set(['%s/result.tar' % r for r in self.results[container]])
        except KeyError:
            self.send_error(401, 'Container does not exist')
            return
        if 'prefix' in query:
            p = query['prefix'][-1]
            objs = set([o for o in objs if o.startswith(p)])
        if 'delimiter' in query:
            d = query['delimiter'][-1]
            # if find() returns a value, we want to include the delimiter, thus
            # bump its result; for "not found" return None
            find_adapter = lambda i: (i >= 0) and (i + 1) or None
            objs = set([o[:find_adapter(o.find(d))] for o in objs])
        if 'marker' in query:
            m = query['marker'][-1]
            objs = set([o for o in objs if o > m])

        self.send_response(objs and 200 or 204)  # 204: "No Content"
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(('\n'.join(sorted(objs)) + '\n').encode('UTF-8'))


class AutoPkgTestSwiftServer:
    def __init__(self, port=8080):
        self.port = port
        self.server_pid = None
        self.log = None

    def __del__(self):
        if self.server_pid:
            self.stop()

    @classmethod
    def set_results(klass, results):
        '''Set served results.

        results is a map: container -> result.tar path ->
           (exitcode, testpkg-version, testinfo)
        '''
        SwiftHTTPRequestHandler.results = results

    def start(self):
        assert self.server_pid is None, 'already started'
        if self.log:
            self.log.close()
        self.log = tempfile.TemporaryFile()
        p = os.fork()
        if p:
            # parent: wait until server starts
            self.server_pid = p
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            while True:
                if s.connect_ex(('127.0.0.1', self.port)) == 0:
                    break
                time.sleep(0.1)
            s.close()
            return

        # child; quiesce logging on stderr
        os.dup2(self.log.fileno(), sys.stderr.fileno())
        srv = HTTPServer(('', self.port), SwiftHTTPRequestHandler)
        srv.serve_forever()
        sys.exit(0)

    def stop(self):
        assert self.server_pid, 'not running'
        os.kill(self.server_pid, 15)
        os.waitpid(self.server_pid, 0)
        self.server_pid = None
        self.log.close()

if __name__ == '__main__':
    srv = AutoPkgTestSwiftServer()
    srv.set_results({'autopkgtest-series': {
        'series/i386/d/darkgreen/20150101_100000@': (0, 'darkgreen 1'),
        'series/i386/g/green/20150101_100000@': (0, 'green 1', {'custom_environment': ['ADT_TEST_TRIGGERS=green']}),
        'series/i386/l/lightgreen/20150101_100000@': (0, 'lightgreen 1'),
        'series/i386/l/lightgreen/20150101_100101@': (4, 'lightgreen 2'),
        'series/i386/l/lightgreen/20150101_100102@': (0, 'lightgreen 3'),
    }})
    srv.start()
    print('Running on http://localhost:8080/autopkgtest-series')
    print('Press Enter to quit.')
    sys.stdin.readline()
    srv.stop()
