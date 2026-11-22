from carlos import urlcheck

# No test touches the network: every host name resolves to a public address unless a test injects its own resolver (#386).
urlcheck.RESOLVER = lambda host, port, **kw: [(2, 1, 6, '', ('93.184.216.34', port))]
