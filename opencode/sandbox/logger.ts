import pino from "pino";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pretty from "pino-pretty";

export type LogFields = Record<string, unknown>;

export type Logger = {
  bind(fields: LogFields): Logger;
  debug(event: string, fields?: LogFields): void;
  info(event: string, fields?: LogFields): void;
  warn(event: string, fields?: LogFields): void;
  error(event: string, fields?: LogFields): void;
};

const PrettyIgnoredKeys = new Set(["level", "time", "pid", "hostname", "msg", "levelLabel"]);

export function createLogger(options: { level?: string } = {}): Logger {
  const stream = pretty({
    colorize: process.stderr.isTTY,
    destination: 2,
    hideObject: true,
    ignore: "pid,hostname",
    messageFormat(log) {
      const event = typeof log.msg === "string" ? log.msg : "log";
      const fields = Object.entries(log)
        .filter(([key]) => !PrettyIgnoredKeys.has(key))
        .map(([key, value]) => `${key}=${formatField(value)}`)
        .join(" ");

      return fields ? `${event} ${fields}` : event;
    },
    sync: true,
    translateTime: "HH:MM:ss",
  });
  const logger = pino({
    base: undefined,
    level: options.level ?? process.env.OPENCODE_SANDBOX_LOG_LEVEL ?? "info",
  }, stream);

  return wrapPino(logger);
}

export const silentLogger: Logger = {
  bind() {
    return silentLogger;
  },
  debug() {},
  info() {},
  warn() {},
  error() {},
};

function wrapPino(logger: pino.Logger): Logger {
  return {
    bind(fields) {
      return wrapPino(logger.child(fields));
    },
    debug(event, fields = {}) {
      logger.debug(enrichFields(fields), event);
    },
    info(event, fields = {}) {
      logger.info(enrichFields(fields), event);
    },
    warn(event, fields = {}) {
      logger.warn(enrichFields(fields), event);
    },
    error(event, fields = {}) {
      logger.error(enrichFields(fields), event);
    },
  };
}

function enrichFields(fields: LogFields): LogFields {
  if (fields.callsite) {
    return fields;
  }

  return { ...fields, callsite: currentCallsite() };
}

function formatField(value: unknown): string {
  if (typeof value === "string") {
    return /\s/.test(value) ? JSON.stringify(value) : value;
  }
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return String(value);
  }
  return JSON.stringify(value);
}

function currentCallsite(): string {
  // Capturing TypeScript file/line data requires stack inspection, which is
  // relatively expensive. Use callsite logging with care and avoid adding extra
  // stack inspection on hot paths. This should eventually be gated behind an
  // environment variable, the same way pretty console logging should eventually
  // be gated behind an environment variable.
  const stack = new Error().stack ?? "";
  const frame = stack
    .split("\n")
    .slice(1)
    .map((line) => line.trim())
    .find((line) => !line.includes("logger.js") && !line.includes("logger.ts") && !line.includes("node:internal"));

  return frame ? normalizeCallsite(frame) : "unknown";
}

function normalizeCallsite(frame: string): string {
  const withoutPrefix = frame.replace(/^at\s+/, "");
  const match = withoutPrefix.match(/^(?:(.*?) \()?(.+):(\d+):(\d+)\)?$/);

  if (!match) {
    return withoutPrefix;
  }

  const [, label, rawFile, line, column] = match;
  const file = normalizeFilePath(rawFile);
  const location = `${file}:${line}:${column}`;

  return label ? `${label} (${location})` : location;
}

function normalizeFilePath(value: string): string {
  try {
    const filePath = value.startsWith("file://") ? fileURLToPath(value) : value;
    const relative = path.relative(process.cwd(), filePath);
    return relative && !relative.startsWith("..") && !path.isAbsolute(relative) ? relative : filePath;
  } catch {
    return value;
  }
}
