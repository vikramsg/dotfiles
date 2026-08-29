package config

import (
	"encoding/json"
	"fmt"
	"os"
)

type Config struct {
	Host string `json:"host"`
}

func Load(path string) (Config, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		return Config{}, fmt.Errorf("read configuration: %w", err)
	}
	var configuration Config
	if err := json.Unmarshal(contents, &configuration); err != nil {
		return Config{}, fmt.Errorf("decode configuration: %w", err)
	}
	if configuration.Host == "" {
		return Config{}, fmt.Errorf("configuration host is required")
	}
	return configuration, nil
}
