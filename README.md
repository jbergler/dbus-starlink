
Enable Local Network Access:
The Starlink mobile app (version 2022.09.0 or later) is required to enable local network access to location data. This setting is found under SETTINGS -> ADVANCED -> DEBUG DATA -> STARLINK LOCATION -> allow access on local network. 


# Development docs

### Updating protos with protoc
uv run python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. dishy.pr
oto