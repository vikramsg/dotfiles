## Language Essentials

### Types

```typescript
string
number
boolean
null
undefined
string[]
Array<string>
object
unknown
any
```

**Object**

```typescript
const user: { name: string; age: number } = {
  name: "Ada",
  age: 30,
};
```

**Interface**

```typescript
// An interface describes the shape of an object.
interface User {
  name: string;
  age: number;
}
const user: User = {
  name: "Ada",
  age: 30,
};
```

**Type**

```typescript
//A type can also describe an object:
type User = {
  name: string;
  age: number;
};

// For simple object shapes, this is almost the same as interface.
// But type can do more things like unions:
type ID = string | number;
type Status = "pending" | "success" | "error";
type UserOrNull = User | null;
```

**Enum**

```typescript
enum Status {
  Pending,
  Success,
  Error,
}

// Usage:
const status: Status = Status.Pending;

// By default, these are numeric:
Status.Pending // 0
Status.Success // 1
Status.Error   // 2

// NOTE: 2. String Enums
// Usually better than numeric enums:
enum Status {
  Pending = "pending",
  Success = "success",
  Error = "error",
}
// Usage:
const status: Status = Status.Pending;
// This gives you real runtime values:
console.log(Status.Pending); // "pending"

// 7. Common Usage With switch
type Status = "pending" | "success" | "error";
function messageForStatus(status: Status): string {
  switch (status) {
    case "pending":
      return "Still working";
    case "success":
      return "Done";
    case "error":
      return "Failed";
  }
}

// With enum:
enum Status {
  Pending = "pending",
  Success = "success",
  Error = "error",
}
function messageForStatus(status: Status): string {
  switch (status) {
    case Status.Pending:
      return "Still working";
    case Status.Success:
      return "Done";
    case Status.Error:
      return "Failed";
  }
}

// Use types instead
type Status = "pending" | "success" | "error";

// If you want named constants too:
const Status = {
  Pending: "pending",
  Success: "success",
  Error: "error",
} as const;
type Status = typeof Status[keyof typeof Status];
// Use built-in enum when your codebase already uses it heavily, or when a framework/library expects it.
```

## Running Essentials

### Using build scripts defined in `package.json`

```bash
npm run <script defined in package.json>

## For example
npm run build # If build is a script name in package.json
```

### Building Typescript

Node does not directly run Typescript.
So we have to build/compile into Javascript and then node runs it.

The following will build using the TypeScript compiler.
File locations and config are defined in the config file.
```bash
tsc -p sandbox/tsconfig.json
```


