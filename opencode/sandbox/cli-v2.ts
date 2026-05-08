import { cac } from "cac"
import { pathToFileURL } from "node:url"

type CliIO = {
  stdout: {
    write(text: string): void
  }
  stderr: {
    write(text: string): void
  }
}

export function createCli(io: CliIO = { stdout: process.stdout, stderr: process.stderr }) {
  const cli = cac("cli-v2")

  cli.command("hello", "Print hello world").action(() => {
    io.stdout.write("hello world\n")
  })

  cli.help()
  return cli
}

export async function runCli(argv = process.argv, io?: CliIO): Promise<number> {
  const cli = createCli(io)

  try {
    cli.parse(argv, { run: false })
    await cli.runMatchedCommand()
    return 0
  } catch (error) {
    const target = io?.stderr || process.stderr
    target.write(`${(error as Error).message}\n`)
    return 1
  }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await runCli()
}
