package main

import (
	"fmt"
	"os"

	"github.com/vikramsg/dotfiles/bin/zwm/internal/app"
	"github.com/vikramsg/dotfiles/bin/zwm/internal/cli"
)

func main() {
	if err := cli.Execute(os.Args[1:], app.New()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
