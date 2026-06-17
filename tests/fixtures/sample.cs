using System;
using System.Collections.Generic;

interface IGreetable {
    string Greet(string name);
}

class Greeter : IGreetable {
    public string Greet(string name) {
        return $"Hello, {name}!";
    }
}

class Program {
    static Greeter CreateGreeter() {
        return new Greeter();
    }

    static void Main(string[] args) {
        Greeter g = CreateGreeter();
        string msg = g.Greet("World");
        Console.WriteLine(msg);
    }

    const string DefaultName = "World";
}
