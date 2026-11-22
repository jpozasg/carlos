"""One check for every URL that comes from outside and that the server, the worker or a helper will fetch or hand to a browser
(request `url`, later photo URLs): a plain public http(s) link. No credentials in the URL, no IP literal, no localhost or
internal names, no unusual port, and every address the name resolves to must be globally routable (so 127.0.0.1, 10/8,
192.168/16, 169.254/16 incl. the cloud metadata address, CGNAT, ::1 and fc00::/7 are refused, also behind a DNS name such as
nip.io or a decimal address like 2130706433).
shortcut: the name is resolved here and again by the fetcher, so a DNS rebinding answer in between is not caught (the worker
checks again just before a run, which narrows the window); pin the resolved address in the fetcher if that is ever needed."""
import ipaddress, socket
from urllib.parse import urlsplit

RESOLVER = socket.getaddrinfo  # tests replace it: no network
INTERNAL_SUFFIXES = ('.localhost', '.local', '.localdomain', '.internal', '.intranet', '.lan', '.home', '.home.arpa', '.corp')


def public_http_url(url, resolver=None):
    """`url` unchanged when it is a public http(s) link; ValueError('url: ...') saying why otherwise."""
    try:
        u = urlsplit(str(url or '').strip())
        host, port = (u.hostname or '').rstrip('.').lower(), u.port
    except ValueError:
        raise ValueError('url: not a valid link') from None
    if u.scheme not in ('http', 'https') or not host:
        raise ValueError('url: an http(s) link')
    if u.username is not None or u.password is not None:
        raise ValueError('url: a link without a user name or password')
    if port not in (None, 80, 443):
        raise ValueError('url: a link on the standard web port (80 or 443)')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('url: a host name, not an IP address')
    if host == 'localhost' or host.endswith(INTERNAL_SUFFIXES) or host.rsplit('.', 1)[-1].isdigit():  # a numeric last label is an odd IPv4 spelling (127.1)
        raise ValueError('url: a public host name')
    try:
        found = (resolver or RESOLVER)(host, port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError('url: the host name does not resolve (check the link or try again)') from None
    if not found:
        raise ValueError('url: the host name does not resolve (check the link or try again)')
    for info in found:
        ip = ipaddress.ip_address(info[4][0].split('%')[0])
        ip = getattr(ip, 'ipv4_mapped', None) or ip  # ::ffff:127.0.0.1 is 127.0.0.1
        if not ip.is_global:
            raise ValueError('url: the host name points to a private or reserved address')
    return str(url).strip()
