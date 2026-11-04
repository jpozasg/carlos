"""Entry point: python app.py [--export-md]. The code is in the carlos package; the data in CARLOS_DATA (default ./data)."""
import sys
from carlos.server import main

if __name__ == '__main__':
    main(sys.argv[1:])
