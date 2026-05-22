const numbers: number[] = [1, 2, 3, 4, 5, 6];

const names: string[] = ["Ada", "Grace", "Linus", "Guido"];

const flags: boolean[] = [true, false, true, false];

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

type Product = {
  name: string;
  price: number;
  inStock: boolean;
};

const products: Product[] = [
  { name: "Keyboard", price: 100, inStock: true },
  { name: "Mouse", price: 50, inStock: false },
  { name: "Monitor", price: 300, inStock: true },
  { name: "Desk", price: 450, inStock: false },
];

type Order = {
  id: string;
  total: number;
  status: "pending" | "paid" | "cancelled";
};

const orders: Order[] = [
  { id: "order-001", total: 125, status: "paid" },
  { id: "order-002", total: 80, status: "pending" },
  { id: "order-003", total: 240, status: "cancelled" },
  { id: "order-004", total: 60, status: "paid" },
];

console.log("numbers", numbers);
console.log("names", names);
console.log("flags", flags);
console.log("users", users);
console.log("products", products);
console.log("orders", orders);
