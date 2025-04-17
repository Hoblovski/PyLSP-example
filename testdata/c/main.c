#include <stdio.h>
struct IntPair {
        int a;
        int b; };
typedef struct IntPair StructIntPair;
void swapPair(StructIntPair *a) {
        int c = a->a;
        a->b = a->a;
        a->a = c;  }
union IntOrChar {
        int i;
        char c; };
extern int add(int, int);
int compare(const void *a, const void *b) {
    int int_a = *((int *)a);
    int int_b = *((int *)b);
    if (int_a < int_b) return -1;
    if (int_a > int_b) return 1;
    return 0;  }
static int foobar(int a) {
        return a+1; }
    return 0;  }
int main() {
    int x = add(2, 3);
    printf("%d\n", x);
    return 0;  }
