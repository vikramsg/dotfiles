import { cac } from "cac";
import { pathToFileURL } from "node:url";

type Writer = {
  write(text: string): unknown;
};

type CliIO = {
  stdout: Writer;
  stderr: Writer;
};

const Command = {
  Hello: "hello",
  Test: "test",
} as const;

type Command = (typeof Command)[keyof typeof Command];

const defaultIO: CliIO = {
  stdout: process.stdout,
  stderr: process.stderr,
};

function something() {
  /**
   * We will use this function to tinker around. We will **NOT** try to figure out
   * how to use the CLI parser right now.
   * That is for next week.
   **/
  console.log("I am here!");
}

export function createCli(io: CliIO = defaultIO) {
  const cli = cac("cli-v2");

  cli.command(Command.Hello, "Print hello world").action(() => {
    io.stdout.write("hello world\n");
  });
  cli.command(Command.Test, "Tinker testing").action(() => {
    something();
  });

  cli.help();
  return cli;
}

export async function runCli(
  argv = process.argv,
  io: CliIO = defaultIO,
): Promise<number> {
  const cli = createCli(io);

  // Only parse, do not run when doing run: false
  const parsed = cli.parse(argv, { run: false });

  if (!cli.matchedCommand && cli.args.length > 0) {
    io.stderr.write(`Unknown command: ${parsed.args.join(" ")}\n`);
    cli.outputHelp();
    return 1;
  }

  if (cli.args.length === 0) {
    io.stderr.write(`No command provided.`);
    cli.outputHelp();
    return 1;
  }

  await cli.runMatchedCommand();
  return 0;
}

// When Node executes this file directly, process.argv[1] is the filesystem path
// to this script. Convert it to a file:// URL so it can be compared with
// import.meta.url, which is always represented as a URL in ES modules.
const entrypoint = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";

// Only run the CLI entrypoint for direct execution, not when tests or other
// modules import createCli/runCli. Assigning process.exitCode lets Node finish
// normal cleanup before exiting with the status returned by runCli().
if (import.meta.url === entrypoint) {
  process.exitCode = await runCli();
}
