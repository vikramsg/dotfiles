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
