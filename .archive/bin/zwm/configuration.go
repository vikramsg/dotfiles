package zwm

import (
	"encoding/json"
	"fmt"
	"os"
)

type Configuration struct {
	Host string `json:"host"`
}

func LoadConfiguration(path string) (Configuration, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		return Configuration{}, fmt.Errorf("read configuration: %w", err)
	}
	var configuration Configuration
	if err := json.Unmarshal(contents, &configuration); err != nil {
		return Configuration{}, fmt.Errorf("decode configuration: %w", err)
	}
	if configuration.Host == "" {
		return Configuration{}, fmt.Errorf("configuration host is required")
	}
	return configuration, nil
}
