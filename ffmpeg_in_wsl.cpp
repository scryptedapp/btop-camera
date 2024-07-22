#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <cstdlib>

int main(int argc, char* argv[]) {
    // Create the command string
    std::stringstream command;
    command << "wsl.exe -e";

    // The command will run within bash
    command << " bash -c";

    // Get host ip by checking WSL default route
    command << " 'host_ip=$(ip route | awk \"/default/ {print \\$3}\");";

    // Set XAUTHORITY
    command << " export XAUTHORITY=/tmp/.scrypted_btop/Xauthority;";

    // We want to run ffmpeg
    command << " ffmpeg";

    // Append all arguments to the command
    for (int i = 1; i < argc; ++i) {
        // If the argument contains an ip and it's localhost or 127.0.0.1,
        // replace it with the host ip
        std::string arg = argv[i];
        if (arg.find("localhost") != std::string::npos) {
            arg.replace(arg.find("localhost"), 9, "$host_ip");
        } else if (arg.find("127.0.0.1") != std::string::npos) {
            arg.replace(arg.find("127.0.0.1"), 9, "$host_ip");
        }
        command << " " << arg;
    }

    // Close the single quote
    command << "'";

    // Convert the command to a string
    std::string commandStr = command.str();

    // Execute the command in a subshell
    int result = std::system(commandStr.c_str());

    // Return the result of the system call
    return result;
}
