class CommentEdgeCases {

  // function commentedOut() : boolean {
  //   return true
  // }

  function real() : boolean {
    var s = "function notAReference() { }"
    return checkThing()
  }

  /*
  class FakeClass {
    function fake() : boolean {
      return true
    }
  }
  */

  function checkThing() : boolean {
    return true
  }

}
