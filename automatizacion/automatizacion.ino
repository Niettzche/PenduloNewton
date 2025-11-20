#include <Servo.h>
#include <string.h>

#define PIN_SERVO 6
#define STEP_DELAY 20
#define STEP_SIZE 5

Servo servo;
const char OPEN_CMD[] = "OPENSIGNAL";
char serial_buffer[32];
uint8_t serial_idx = 0;

void moveServo(int angulo) {
  servo.write(angulo);
  delay(STEP_DELAY);
}

void openAndCloseServo() {
  moveServo(180);
  delay(2000);
  moveServo(90);
}

void handleSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      // Si no hay nada en el buffer, ignora (esto pasa con CRLF: primero \r, luego \n)
      if (serial_idx == 0) {
        return;
      }

      serial_buffer[serial_idx] = '\0';

      // DEBUG: ver qué llegó exactamente
      Serial.print("[RX] '");
      Serial.print(serial_buffer);
      Serial.println("'");

      if (strcmp(serial_buffer, OPEN_CMD) == 0) {
        Serial.println("[INFO] Comando OPENSIGNAL recibido, moviendo servo");
        digitalWrite(LED_BUILTIN, HIGH);
        openAndCloseServo();
        digitalWrite(LED_BUILTIN, LOW);
      } else {
        Serial.println("[WARN] Comando desconocido");
      }

      // reset para el siguiente comando
      serial_idx = 0;
      return;
    }

    if (serial_idx < sizeof(serial_buffer) - 1) {
      serial_buffer[serial_idx++] = c;
    } else {
      Serial.println("[WARN] Buffer serial lleno, limpiando.");
      serial_idx = 0;
    }
  }
}

void setup() {
  Serial.begin(9600);
  servo.attach(PIN_SERVO);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.println("[INFO] Servo listo");


}

void loop() {
  handleSerial();
}

