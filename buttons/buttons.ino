// Reply to the host's "id" command so it can find this board on any serial port.
const char deviceId[] = "toggl-buttons v1";

const int numButtons = 5;
const int buttonPins[numButtons] = {9, 10, 11, 12, 13};
const int ledPins[numButtons] = {4, 5, 6, 7, 8};

int buttonStates[numButtons] = {0, 0, 0, 0, 0};
int lastButtonStates[numButtons] = {0, 0, 0, 0, 0};
int ledStates[numButtons] = {0, 0, 0, 0, 0};

unsigned long lastDebounceTimes[numButtons] = {0, 0, 0, 0, 0};
unsigned long debounceDelay = 2;

struct BlinkState {
  unsigned long previousMillis = 0;
  int blinkCount = 0;
  int totalBlinks = 0;
  int ledState = LOW;
  int period = 0;
  int initialState = LOW;
};

BlinkState blinkStates[numButtons];

void setup() {
  for (int i = 0; i < numButtons; i++) {
    pinMode(ledPins[i], OUTPUT);
    pinMode(buttonPins[i], INPUT_PULLUP);
  }
  Serial.begin(115200);
}

void loop() {
  if (Serial.available() > 0) {
    String incomingData = Serial.readStringUntil('\n');
    if (incomingData.length() > 0) {
      handleSerialCommand(incomingData);
    }
  }

  for (int i = 0; i < numButtons; i++) {
    int reading = digitalRead(buttonPins[i]);
    if (reading != lastButtonStates[i]) {
      lastDebounceTimes[i] = millis();
    }

    if ((millis() - lastDebounceTimes[i]) > debounceDelay) {
      if (reading != buttonStates[i]) {
        buttonStates[i] = reading;
        if (buttonStates[i] == LOW) {
          turnOnLED(i);
        }
      }
    }
    lastButtonStates[i] = reading;
  }

  updateBlinkingLEDs();
}

void handleSerialCommand(String command) {
  command.trim();
  if (command == "id") {
    Serial.println(deviceId);
  } else if (command == "state") {
    int ledOn = -1;
    for (int i = 0; i < numButtons; i++) {
      if (ledStates[i] == HIGH) {
        ledOn = i + 1;
        break;
      }
    }
    Serial.println(ledOn);
  } else if (command.startsWith("b")) {
    int ledNumber = command.substring(1, 2).toInt();
    int period = command.substring(2, 3).toInt() * 100;
    int blinks = command.substring(3).toInt();
    if (ledNumber >= 1 && ledNumber <= numButtons) {
      blinkLED(ledNumber - 1, period, blinks);
    }
  } else if (command.startsWith("l")) {
    int ledNumber = command.substring(1).toInt();
    if (ledNumber == 0) {
      clearLEDs();
    } else if (ledNumber >= 1 && ledNumber <= numButtons) {
      turnOnLED(ledNumber - 1);
    }
  }
}

void clearLEDs() {
  for (int i = 0; i < numButtons; i++) {
    digitalWrite(ledPins[i], LOW);
    ledStates[i] = LOW;
    blinkStates[i].blinkCount = blinkStates[i].totalBlinks * 2;
    blinkStates[i].initialState = LOW;
  }
}

void turnOnLED(int ledIndex) {
  clearLEDs();
  digitalWrite(ledPins[ledIndex], HIGH);
  ledStates[ledIndex] = HIGH;
  blinkStates[ledIndex].initialState = HIGH;
}

void blinkLED(int ledIndex, int period, int blinks) {
  blinkStates[ledIndex].blinkCount = 0;
  blinkStates[ledIndex].totalBlinks = blinks;
  blinkStates[ledIndex].period = period;
  blinkStates[ledIndex].previousMillis = millis();
  blinkStates[ledIndex].initialState = ledStates[ledIndex];
  blinkStates[ledIndex].ledState = ledStates[ledIndex];
}

void updateBlinkingLEDs() {
  for (int i = 0; i < numButtons; i++) {
    if (blinkStates[i].blinkCount < blinkStates[i].totalBlinks * 2) {
      unsigned long currentMillis = millis();
      if (currentMillis - blinkStates[i].previousMillis >= (blinkStates[i].period / 2)) {
        blinkStates[i].previousMillis = currentMillis;
        blinkStates[i].ledState = !blinkStates[i].ledState;
        digitalWrite(ledPins[i], blinkStates[i].ledState);

        if (blinkStates[i].ledState == blinkStates[i].initialState) {
          blinkStates[i].blinkCount++;
        }
      }
    } else {
      digitalWrite(ledPins[i], blinkStates[i].initialState);
      ledStates[i] = blinkStates[i].initialState;
    }
  }
}
