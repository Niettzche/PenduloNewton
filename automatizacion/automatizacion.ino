#include <Servo.h>

#define PIN_SERVO 6
#define STEP_DELAY 20   
#define STEP_SIZE 5     

Servo servo;
bool open_signal = 0;
int i = 0;

void moveServo(int angulo) {
  servo.write(angulo);
  delay(STEP_DELAY);
}

void setup() {
  Serial.begin(9600);
  servo.attach(PIN_SERVO);
  Serial.println("[INFO] Servo listo");
  moveServo(90);
  delay(1000);
}

void loop() {
  Serial.println("[INFO] Uwu");
  //Si se recibe senal de abrir, mover 180
  /*
  if open_signal == 1{
    moveServo(180); //esperar 5 segundos y volver a cerrar
    delay(2000);
    moveServo(90);
  }
  */

  delay(10000);

  moveServo(180);
  delay(2000);
  moveServo(90);
}
