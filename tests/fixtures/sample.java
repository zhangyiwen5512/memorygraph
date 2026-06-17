package com.example;

import java.util.List;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public int multiply(int a, int b) {
        return a * b;
    }
}

class Main {
    public static void main(String[] args) {
        Calculator calc = new Calculator();
        int result = calc.add(1, 2);
        System.out.println(result);
    }

    static final int DEFAULT = 0;
}
