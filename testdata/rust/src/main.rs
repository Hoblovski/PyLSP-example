// $ rustc main.rs --emit=obj
#[derive(Debug)]
struct IntPair {
    a: i32,
    b: i32,  }
fn swap_pair(pair: &mut IntPair) {
    let c = pair.a;
    pair.b = pair.a;
    pair.a = c;  }
enum IntOrChar {
    I(i32),
    C(u8)  }
fn add(a: i32, b: i32) -> i32 {
    a + b  }
fn compare(a: &i32, b: &i32) -> i32 {
    if a < b {
        -1
    } else if a > b {
        1
    } else {
        0
    }  }
fn main() {
    let x = add(2, 3);
    println!("{}", x);  }
