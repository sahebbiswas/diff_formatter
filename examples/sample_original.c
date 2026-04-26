#include <stdio.h>
#include <stdlib.h>

int main(int argc, char**argv) {
    int x=5,y=10;
    if(x>0){
        printf("Positive\n");
    } else {
        printf("Non-positive\n");
    }

    for(int i=0;i<10;i++) {
        // This line is intentionally very very very very very very very very very very very long to test line length rule
        printf("%d\n", i);
    }

    return 0;
}
