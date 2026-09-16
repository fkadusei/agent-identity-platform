module github.com/fkadusei/enterprise-agent-nhi/spire-plugin

go 1.25.0

// Pinned to the same plugin SDK revision SPIRE 1.12.4 itself builds against,
// so the gRPC plugin protocol lines up exactly.
require github.com/spiffe/spire-plugin-sdk v1.4.4-0.20250606112051-68609d83ce7c

require (
	github.com/hashicorp/go-hclog v1.6.3
	google.golang.org/grpc v1.83.2
	google.golang.org/protobuf v1.36.12
)

require (
	github.com/fatih/color v1.13.0 // indirect
	github.com/golang/protobuf v1.5.4 // indirect
	github.com/hashicorp/go-plugin v1.6.3 // indirect
	github.com/hashicorp/yamux v0.1.1 // indirect
	github.com/mattn/go-colorable v0.1.12 // indirect
	github.com/mattn/go-isatty v0.0.17 // indirect
	github.com/oklog/run v1.0.0 // indirect
	golang.org/x/net v0.58.0 // indirect
	golang.org/x/sys v0.47.0 // indirect
	golang.org/x/text v0.41.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260904194346-d0f1323225a4 // indirect
)
