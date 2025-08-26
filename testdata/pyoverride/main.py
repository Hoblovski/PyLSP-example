class A:
    def __init__(self):
        self.value = 10

    def get_value(self):
        return self.value
    
    def __add__(self, other):
        if isinstance(other, A):
            return A(self.value + other.value)
        return NotImplemented
    
def main():
    a1 = A()
    a2 = A()
    
    print("Value of a1:", a1.get_value())
    print("Value of a2:", a2.get_value())
    
    a3 = a1 + a2
    print("Value of a3 (a1 + a2):", a3.get_value())
