package dev.mr3a.arena;
import java.io.*;
import java.net.*;
import java.util.Arrays;
public final class RenderRelay {
 static void pump(InputStream in,OutputStream out)throws IOException{
  byte[] buffer=new byte[65536];int n;
  while((n=in.read(buffer))>=0){if(n>0)out.write(buffer,0,n);}
 }
 public static void main(String[] args)throws Exception{
  int target=Integer.parseInt(args[0]);byte[] token=args[1].getBytes("US-ASCII");
  if(target<1024||target>65535||token.length!=32)throw new IllegalArgumentException();
  try(ServerSocket listener=new ServerSocket(0,1)){
   listener.setSoTimeout(5000);System.out.println(listener.getLocalPort());System.out.flush();
   try(Socket host=listener.accept()){
    host.setTcpNoDelay(true);host.setSoTimeout(3000);
    byte[] supplied=new byte[32];new DataInputStream(host.getInputStream()).readFully(supplied);
    if(!Arrays.equals(token,supplied))throw new IOException("Authentication failed");
    try(Socket game=new Socket("127.0.0.1",target)){
     game.setTcpNoDelay(true);game.getOutputStream().write(token);host.setSoTimeout(0);
     Thread up=new Thread(new Runnable(){public void run(){try{pump(host.getInputStream(),game.getOutputStream());}catch(IOException ignored){}}});
     up.setDaemon(true);up.start();pump(game.getInputStream(),host.getOutputStream());
    }
   }
  }
 }
}
