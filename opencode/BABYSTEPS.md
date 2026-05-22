## Language Essentials

### Types

```typescript
string
number
boolean
null
undefined
string[] // This is an array
Array<string> // Same as string[]
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

### Arrays

Recall that arrays can be defines in the following manner.

```typescript
string[] // This is an array
Array<string> // Same as string[]
```

But how we do we array wide operations?
In Python we can usually do list or dict comprehensions.
In Typescript, we use the `map` or `filter` functions that can be applied directly to arrays.
For eg.

```typescript
type User = {
  name: string;
  age: number;
  active: boolean;
};

const users: User[] = [
  { name: "Ada", age: 30, active: true },
  { name: "Grace", age: 25, active: false },
  { name: "Linus", age: 54, active: true },
  { name: "Guido", age: 68, active: false },
];

const adaUser = users.filter((user)=>{return user.name === "Ada"}); // Will return only the user named Ada
const adaUser = users.filter((user)=> user.name === "Ada" ); // Does the same thing, but notice that we can omit the return if we got rid of {} 
// [ { name: 'Ada', age: 30, active: true } ]

const userMap = users.map((user) => user.active); // Creates an array of booleans 
// [ true, false, true, false ]

interface UserStatus {
  name: string;
  status: boolean;
}
const newMap: UserStatus[] = users.map((user) => ({
  name: user.name,
  status: false,
})); // Creates a new array from existing array
// [ 
//   { name: 'Ada', status: false }, 
//   { name: 'Grace', status: false }, 
//   { name: 'Linus', status: false }, 
//   { name: 'Guido', status: false } 
// ] 

const adaUser = users.find((user) => user.name === "Ada");
// { name: "Ada", age: 30, active: true }
```

**Rules of thumb**:
```
map    // transform every item into a new array
filter // keep all matching items
find   // return the first matching item, or undefined
```

**Note**

`map` and `filter` do not modify the original array. They return a new array. 
This is a big reason they are idiomatic.


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

### Debugging

**Using a REPL**

```typescript
import repl from "node:repl";

repl.start({ prompt: "debug> " });
```

## Prompt

```
You will act as a typescript teacher. 
You will not look at any files unless I ask you to. 
I know Python well including Pydantic but I am taking babysteps with Typescript
```
