use std::fmt;

trait Greetable {
    fn greet(&self) -> String;
}

struct Person {
    name: String,
}

impl Greetable for Person {
    fn greet(&self) -> String {
        format!("Hello, {}!", self.name)
    }
}

fn new_person(name: &str) -> Person {
    Person { name: name.to_string() }
}

fn main() {
    let p = new_person("World");
    let msg = p.greet();
    println!("{}", msg);
}

const DEFAULT_NAME: &str = "World";
