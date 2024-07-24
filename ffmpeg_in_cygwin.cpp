#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <cstdlib>
#include <cstring>

int main(int argc, char* argv[]) {
    // Get the executable from the environment variable
    const char* executable = std::getenv("CYGWIN_LAUNCHER");
    if (executable == nullptr) {
        std::cerr << "Error: Environment variable CYGWIN_LAUNCHER is not set." << std::endl;
        return 1;
    }

    // Create the command string
    std::stringstream command;
    command << "powershell.exe -Command \"" << executable << '"';

    // We want to run ffmpeg
    command << " \"ffmpeg";

    // Append all arguments to the command
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        command << " " << arg;
    }

    // Close the ffmpeg command
    command << "\"";

    // Convert the command to a string
    std::string commandStr = command.str();

    // Print the command
    std::cout << "Command: " << commandStr << std::endl;

    // Execute the command in a subshell
    int result = std::system(commandStr.c_str());

    // Return the result of the system call
    return result;
}
