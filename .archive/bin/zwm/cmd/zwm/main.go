package main

import (
	"fmt"
	"os"

	"zwm"
	"zwm/internal/cli"
)

func main() {
	if err := cli.Execute(os.Args[1:], zwm.NewFactory()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
