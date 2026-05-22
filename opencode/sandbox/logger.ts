import pino, { type Logger as PinoLogger } from "pino";
import pretty from "pino-pretty";

export type LogFields = Record<string, unknown>;

export type Logger = {
  bind(fields: LogFields): Logger;
  debug(event: string, fields?: LogFields): void;
  info(event: string, fields?: LogFields): void;
  warn(event: string, fields?: LogFields): void;
  error(event: string, fields?: LogFields): void;
};

export const silentLogger: Logger = {
  bind() {
    return silentLogger;
  },
  debug() {},
  info() {},
  warn() {},
  error() {},
};

function fromPino(base: PinoLogger): Logger {
  return {
    bind(fields: LogFields) {
      return fromPino(base.child(fields));
    },
    debug(event: string, fields?: LogFields) {
      base.debug(fields ?? {}, event);
    },
    info(event: string, fields?: LogFields) {
      base.info(fields ?? {}, event);
    },
    warn(event: string, fields?: LogFields) {
      base.warn(fields ?? {}, event);
    },
    error(event: string, fields?: LogFields) {
      base.error(fields ?? {}, event);
    },
  };
}

export function createLogger(): Logger {
  const stream = pretty({
    destination: 2,
    ignore: "pid,hostname",
    sync: true,
    translateTime: "SYS:standard",
  });
  const base = pino(
    {
      level: process.env.OPENCODE_SANDBOX_LOG_LEVEL ?? "info",
    },
    stream,
  );

  return fromPino(base);
}
