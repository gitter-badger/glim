# application initiation script
import os, sys, traceback
from glim.core import Facade, Config as config, IoC as ioc
from glim.component import View as view
from glim.db import Database as database, Orm as orm
from glim.facades import Config, Database, Orm, Session, Cookie, IoC, View

from werkzeug.serving import run_simple
from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.wsgi import SharedDataMiddleware
from werkzeug.utils import redirect
from werkzeug.contrib.sessions import FilesystemSessionStore

from termcolor import colored

def import_module(module, frm):

    try:

        m = __import__(module, fromlist = [frm])
        return m

    except Exception, e:

        print traceback.format_exc()
        exit()

class Glim:

    def __init__(self, urls = {}, config = {}):

        self.config = config

        try:
            self.session_store = FilesystemSessionStore(self.config['sessions']['path'])
        except:
            self.session_store = None

        ruleset = self.flatten_urls(urls)
        rule_map = []
        for url,rule in ruleset.items():
            rule_map.append(Rule(url, endpoint = rule))

        self.url_map = Map(rule_map)

    def flatten_urls(self, urls, current_key = "", ruleset = {}):

        for key in urls:
            # If the value is of type `dict`, then recurse with the value
            if isinstance(urls[key], dict):
                self.flatten_urls(urls[key], current_key + key)
            # Else if the value is type of list, meaning it is a filter
            elif isinstance(urls[key], (list, tuple)):
                k = ','.join(urls[key])
                ruleset[current_key + key] = k
            else:
                ruleset[current_key + key] = urls[key]

        return ruleset

    def dispatch_request(self, request):

        adapter = self.url_map.bind_to_environ(request.environ)

        try:

            endpoint, values = adapter.match()
            mcontroller = import_module('app.controllers', 'controllers')

            # detect filters
            filters = endpoint.split(',')
            endpoint_pieces = filters[-1].split('.')

            # if there exists any filter defined
            if len(filters) > 1:

                filters = filters[:-1]
                # here run filters
                for f in filters:

                    fpieces = f.split('.')
                    cls = fpieces[0]
                    fnc = fpieces[1]
                    mfilter = import_module('app.controllers', 'controllers')
                    obj = getattr(mfilter, cls)
                    ifilter = obj(request)
                    raw = getattr(ifilter, fnc)(** values)

                    if isinstance(raw, basestring):
                        return Response(raw)

                    if isinstance(raw, Response):
                        return raw

            cls = endpoint_pieces[0]

            restful = False
            try:
                fnc = endpoint_pieces[1]
            except:
                restful = True
                fnc = None

            obj = getattr(mcontroller, cls)
            instance = obj(request)

            raw = None
            if restful:
                raw = getattr(instance, request.method.lower()(** values))
            else:
                raw = getattr(instance, fnc)(** values)

            if isinstance(raw, Response):
                return raw
            else:
                return Response(raw)

        except HTTPException, e:
            return e

    def wsgi_app(self, environ, start_response):

        request = Request(environ)

        if self.session_store is not None:

            sid = request.cookies.get(self.config['sessions']['id_header'])

            if sid is None:
                request.session = self.session_store.new()
            else:
                request.session = self.session_store.get(sid)

        response = self.dispatch_request(request)

        if self.session_store is not None:
            if request.session.should_save:
                self.session_store.save(request.session)
                response.set_cookie(self.config['sessions']['id_header'], request.session.sid)

        return response(environ, start_response)

    def __call__(self, environ, start_response):

        return self.wsgi_app(environ, start_response)

class App:

    def __init__(self, env = 'development'):
        self.mconfig = import_module(module = 'app.config.%s' % env, frm = 'config')
        if self.mconfig is None:
            print colored('Configuration for %s not found' % env, 'red')
            print colored('Run the following;', 'yellow')
            print colored('$ cp app/config/default.py app/config/%s.py' % env, 'yellow')
            exit()

        self.boot_config()
        self.boot_db()
        self.boot_facades()
        self.boot_extensions()
        self.boot_ioc()
        self.boot_view()

        # find out start
        mstart = import_module('app.start', 'start')
        self.before = mstart.before

    def boot_config(self):

        registry = self.mconfig.config
        Config.boot(config, registry)

    def boot_db(self):

        if Config.get('db'):
            Database.boot(database, Config.get('db'))
            Orm.boot(orm, Database.engines)

    def boot_facades(self):

        try:

            facades = self.mconfig.facades

            # boot facades
            for facade in facades:
                core_mstr = 'glim.core'
                facade_mstr = 'glim.facades'

                fromlist = facade

                core_module = import_module(core_mstr, facade)
                facade_module = import_module(facade_mstr, facade)

                core_class = getattr(core_module, facade)
                facade_class = getattr(facade_module, facade)

                cfg = Config.get(facade.lower())
                facade_class.boot(core_class, cfg)

        except Exception, e:

            print traceback.format_exc()
            exit()

    def boot_extensions(self, extensions = []):

        try:

            extensions = self.mconfig.extensions

            for extension in extensions:

                extension_config = Config.get('extensions.%s' % extension)
                extension_mstr = 'ext.%s' % extension
                extension_module = import_module(extension_mstr, extension)

                extension_class = getattr(extension_module, extension.title())

                # check if extension is bootable
                if issubclass(extension_class, Facade):

                    cextension_class = getattr(extension_module, '%sExtension' % (extension.title()))
                    extension_class.boot(cextension_class, extension_config)

        except Exception, e:

            print traceback.format_exc()
            exit()

    def boot_ioc(self):
        IoC.boot(ioc)

    def boot_view(self):
        View.boot(view, Config.get('glim.views'))

    def start(self, host = '127.0.0.1', port = '8080', env = 'development', with_static = True):

        try:

            self.before()
            mroutes = import_module('app.routes', 'routes')
            app = Glim(mroutes.urls, Config.get('glim'))

            if with_static:
                dirname = os.path.dirname
                static_path = os.path.join(dirname(dirname(__file__)), 'app/static')
                app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
                    '/static' : static_path
                })

            run_simple(host, int(port), app, use_debugger = Config.get('glim.debugger'), use_reloader = Config.get('glim.reloader'))

        except Exception, e:

            print traceback.format_exc()
            exit()