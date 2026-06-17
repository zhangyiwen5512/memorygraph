package main

import "fmt"

type Greeter struct {
	Name string
}

func (g *Greeter) Greet() string {
	return fmt.Sprintf("Hello, %s!", g.Name)
}

func NewGreeter(name string) *Greeter {
	return &Greeter{Name: name}
}

func main() {
	g := NewGreeter("World")
	msg := g.Greet()
	fmt.Println(msg)
}

var DefaultName = "World"

// Interface
type Reader interface {
	Read(p []byte) (n int, err error)
}
