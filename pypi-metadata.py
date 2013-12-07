# TODO:
#      - check for github/other repo url if there are no releases
#      - check requirements.txt

import sys
import xmlrpclib

import tarfile, re, requests, csv, json
from zipfile import ZipFile
from bz2 import BZ2File
from base64 import b64encode, b64decode
from funcy import first, ikeep, re_find, re_test, distinct, retry, log_errors, compose


def print_alert(message):
    print '\033[1;31m%s\033[1;m' % message

def print_notice(message):
    print "\033[32m%s\033[0m" % message


def _extract_deps(content):
    """ Extract dependencies using install_requires directive """
    # strip comments
    content = re.sub(r'#.*$', '', content, flags=re.M)
    results = re.findall("install_requires=\[([\W'a-zA-Z0-9]*?)\]", content, re.M)
    deps = []
    if results:
        deps = [a.replace("'", "").strip()
                for a in results[0].strip().split(",")
                if a.replace("'", "").strip() != ""]
    return deps


class SetupReadError(Exception):
    pass

def is_setup(filename):
    return filename.count('/') <= 1 and re_test(r'(^|/)setup.py$', filename)

def _extract_setup_content(filename, format):
    """Extract setup.py content as string from downladed tar """
    if format in {'gz', 'bz2'}:
        tar_file = tarfile.open(filename)
        setup_candidates = [elem for elem in tar_file.getmembers() if is_setup(elem.name)]
        reader = lambda name: tar_file.extractfile(name).read()
    elif format == 'zip':
        zip_file = ZipFile(filename)
        setup_candidates = filter(is_setup, zip_file.namelist())
        reader = zip_file.read
    else:
        raise SetupReadError('setup_format')

    if not setup_candidates:
        raise SetupReadError('no_setup')
    elif len(setup_candidates) > 1:
        raise SetupReadError('many_setups')
    else:
        return reader(setup_candidates[0])


def extract_package(name, client = xmlrpclib.ServerProxy('http://pypi.python.org/pypi'), verbose=False):
    with open('pypi-deps.csv', 'a') as file:
        spamwriter = csv.writer(file, delimiter='\t',
                            quotechar='|', quoting=csv.QUOTE_MINIMAL)
        releases = client.package_releases(name)
        if not releases:
            print_alert("%s: no releases" % name)
            spamwriter.writerow([name, '-', '-no_releases'])

        for release in client.package_releases(name):
            if verbose:
                print "Extracting %s release %s" % (name, release)
            doc = client.release_urls(name, release)
            if verbose:
                for d in doc:
                    print d
            urls = [d['url'] for d in doc if not re_test(r'\.(egg|exe|whl)$', d['url'])]

            if urls:
                url = first(urls).replace("http://pypi.python.org/", "http://f.pypi.python.org/")
                if verbose:
                    print "Downloading url %s" % url
                req = requests.get(url)
                if req.status_code != 200:
                    print_alert("%s: download failed with %s" % (name, req.status_code))
                else:
                    with open('/tmp/temp_file', 'w') as f:
                        f.write(req.content)

                    try:
                        content = _extract_setup_content('/tmp/temp_file',
                                                         format=re_find(r'\.(\w+)$', url))
                    except SetupReadError as e:
                        print_alert("%s: version %s setup read error - %s"
                                        % (name, release, e.args[0]))
                        spamwriter.writerow([name, release, '-%s' % e.args[0]])
                        continue
                    except Exception as e:
                        print_alert("%s: version %s: %s" % (name, release, e))
                        spamwriter.writerow([name, release, '-%s' % e.__class__.__name__])
                        continue

                    deps = _extract_deps(content)
                    print '%s: version %s depends on %s' % (name, release, deps)
                    spamwriter.writerow([name, release, b64encode(json.dumps(deps))])
            else:
                print_alert("%s: no release urls" % name)
                spamwriter.writerow([name, release, '-no_urls'])


def load_graph():
    def decode_line(line):
        name, version, deps = line.strip().split('\t')
        deps = json.loads(b64decode(deps)) if not deps.startswith('-') else None
        return (name, version, deps)

    with open('pypi-deps.csv', 'r') as f:
        data = map(decode_line, f)

    return data

def simple_dep(dep):
    dep = dep.strip('"')
    # comment
    if dep.startswith('#'):
        return None
    # some code
    if set('()#\n') & set(dep):
        return None
    # no name
    if re_test(r'^(?:==|>=|<=|>|<|!=|$)', dep):
        return None

    res = re_find(r'^\s*([\w\.\-]+)\s*(?:==|>=|<=|>|<|!=|$)', dep)
    return res.lower() if res else res
    if dep and not res:
        print_alert('dep: %r, res: %r' % (dep, res))
    return res.lower() if res else res

def simple_deps(deps):
    return set(ikeep(simple_dep, deps))

# print sys.argv
action = sys.argv[1] if len(sys.argv) > 1 else 'load'

if action == 'load':
    client = xmlrpclib.ServerProxy('http://pypi.python.org/pypi')
    packages = client.list_packages()
    loaded = {name for name, _, _ in load_graph()}
    print_notice('>>> Packages %d, loaded %d' % (len(packages), len(loaded)))
    print_notice('>>> %d to go...' % (len(packages) - len(loaded)))

    try_harder = compose(
        retry(3, xmlrpclib.ProtocolError),
        log_errors(print_alert)
    )
    harder_extract = try_harder(extract_package)

    try:
        for package in packages:
            if package not in loaded:
                harder_extract(package, client, verbose='-v' in sys.argv)
    except KeyboardInterrupt:
        pass


elif action == 'one':
    extract_package(sys.argv[2], verbose=True)

elif action == 'rev':
    seek_for = sys.argv[2]
    loaded = [(name, simple_deps(deps)) for name, _, deps in load_graph() if deps]

    dependants = distinct(name for name, deps in loaded if seek_for in deps)
    print_notice('>>> %d dependants on %s' % (len(dependants), seek_for))
    print dependants[-40:]
