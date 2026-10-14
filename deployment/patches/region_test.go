package api

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestChinaRegionRedirects(t *testing.T) {
	endpoints := ChinaMainlandEndpoints()
	session := NewSession(endpoints)
	if got := session.getSRPAuthHeaders()["X-Apple-OAuth-Redirect-URI"]; got != endpoints.Base {
		t.Fatalf("China OAuth redirect URI = %q; want %q", got, endpoints.Base)
	}
	var redirect string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirect = r.URL.Query().Get("redirect_uri")
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()
	endpoints.Auth = server.URL
	session = NewSession(endpoints)
	if err := session.authStart(context.Background()); err != nil {
		t.Fatal(err)
	}
	if redirect != endpoints.Base {
		t.Fatalf("China authorize redirect URI = %q; want %q", redirect, endpoints.Base)
	}
}

func TestRegionSessionsIndependent(t *testing.T) {
	global := NewSession(EndpointsForRegion("global"))
	china := NewSession(EndpointsForRegion("chinamainland"))
	if global.getAuthOrigin() != "https://idmsa.apple.com" {
		t.Fatal("global auth changed")
	}
	if china.getAuthOrigin() != "https://idmsa.apple.com.cn" {
		t.Fatal("China auth not selected")
	}
	if global.getCommonHeaders(nil)["Origin"] != "https://www.icloud.com" {
		t.Fatal("global origin changed")
	}
	if china.getCommonHeaders(nil)["Origin"] != "https://www.icloud.com.cn" {
		t.Fatal("China origin not selected")
	}
}
