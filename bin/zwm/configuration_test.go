package zwm

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadReadsConfiguredHost(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "config.json")
	if err := os.WriteFile(path, []byte(`{"host":"vm-us"}`), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	configuration, err := LoadConfiguration(path)
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if configuration.Host != "vm-us" {
		t.Fatalf("host = %q, want vm-us", configuration.Host)
	}
}

func TestLoadRejectsMissingHost(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "config.json")
	if err := os.WriteFile(path, []byte(`{}`), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	if _, err := LoadConfiguration(path); err == nil {
		t.Fatal("Load succeeded without a host")
	}
}
