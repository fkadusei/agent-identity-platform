// SPIRE CredentialComposer plugin: adds a `jti` claim to workload JWT-SVIDs.
//
// WHY THIS EXISTS
// Keycloak's OAuth client authentication via private_key_jwt (RFC 7523)
// hard-requires a `jti` claim (its isReusePermitted() is hardcoded false).
// SPIRE's JWT-SVIDs only carry iss/sub/aud/exp/iat, so a JWT-SVID cannot be
// presented as a client assertion without one. Rather than weaken the
// architecture (static client secrets) or misuse Keycloak's X.509 client auth
// (which matches only on subject DN — and SPIRE puts the SPIFFE ID in the SAN,
// not the subject), this plugin supplies the missing claim at issuance.
//
// SPIRE loads external plugins as separate processes over gRPC (hashicorp
// go-plugin); see k8s/spire/spire-server.yaml for the plugin_cmd wiring.
//
// It does NOT touch the SPIFFE ID, audience, expiry, or any other claim.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"

	"github.com/hashicorp/go-hclog"
	"github.com/spiffe/spire-plugin-sdk/pluginmain"
	"github.com/spiffe/spire-plugin-sdk/pluginsdk"
	credentialcomposerv1 "github.com/spiffe/spire-plugin-sdk/proto/spire/plugin/server/credentialcomposer/v1"
	configv1 "github.com/spiffe/spire-plugin-sdk/proto/spire/service/common/config/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/structpb"
)

var _ pluginsdk.NeedsLogger = (*Plugin)(nil)

type Plugin struct {
	credentialcomposerv1.UnimplementedCredentialComposerServer
	configv1.UnimplementedConfigServer
	logger hclog.Logger
}

// ComposeWorkloadJWTSVID is called by SPIRE Server for every workload
// JWT-SVID it mints. We add a unique jti; all other claims pass through
// untouched.
func (p *Plugin) ComposeWorkloadJWTSVID(
	ctx context.Context,
	req *credentialcomposerv1.ComposeWorkloadJWTSVIDRequest,
) (*credentialcomposerv1.ComposeWorkloadJWTSVIDResponse, error) {
	attrs := req.GetAttributes()
	if attrs == nil {
		attrs = &credentialcomposerv1.JWTSVIDAttributes{}
	}

	claims := attrs.GetClaims()
	if claims == nil {
		claims = &structpb.Struct{Fields: map[string]*structpb.Value{}}
	}

	if _, present := claims.Fields["jti"]; !present {
		id, err := randomID()
		if err != nil {
			return nil, status.Errorf(codes.Internal, "failed to generate jti: %v", err)
		}
		claims.Fields["jti"] = structpb.NewStringValue(id)
	}

	attrs.Claims = claims
	return &credentialcomposerv1.ComposeWorkloadJWTSVIDResponse{Attributes: attrs}, nil
}

// Configure accepts (empty) configuration from server.conf's plugin_data block.
func (p *Plugin) Configure(
	ctx context.Context,
	req *configv1.ConfigureRequest,
) (*configv1.ConfigureResponse, error) {
	return &configv1.ConfigureResponse{}, nil
}

func (p *Plugin) SetLogger(logger hclog.Logger) { p.logger = logger }

func randomID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func main() {
	plugin := new(Plugin)
	// Serve blocks forever; SPIRE Server execs this binary and speaks gRPC.
	pluginmain.Serve(
		credentialcomposerv1.CredentialComposerPluginServer(plugin),
		configv1.ConfigServiceServer(plugin),
	)
}
