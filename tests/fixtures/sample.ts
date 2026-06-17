interface Greetable {
  greet(name: string): string;
}

class Person implements Greetable {
  private name: string;

  constructor(name: string) {
    this.name = name;
  }

  greet(name: string): string {
    return `Hello, ${name}, I'm ${this.name}`;
  }
}

function makeGreeter(name: string): Person {
  return new Person(name);
}

function main(): void {
  const p = makeGreeter("Alice");
  const msg = p.greet("Bob");
  console.log(msg);
}

const DEFAULT_NAME: string = "World";
type NameProvider = () => string;
