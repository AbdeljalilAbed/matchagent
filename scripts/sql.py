import sys

import duckdb

con = duckdb.connect("data/matchagent.duckdb", read_only=True)
print(con.execute(sys.argv[1]).df().to_string(index=False))
